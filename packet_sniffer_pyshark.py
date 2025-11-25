#!/usr/bin/env python3
import time, threading, queue, os, json, requests, argparse, logging
from collections import defaultdict, deque

try:
    import pyshark
except Exception as e:
    raise SystemExit("pyshark import failed: install with `pip install pyshark` and ensure tshark is installed. Err: %s" % e)

CAPTURE_INTERFACE = os.environ.get("SNIF_IFACE", "eth0")   # change to your interface (e.g. ens3, eth0)
BPF_FILTER = os.environ.get("SNIF_FILTER", "tcp")         # BPF expression for tshark (tcp by default)
FLOWCOLLECTOR_URL = os.environ.get("FLOWCOLLECTOR_URL", "http://127.0.0.1:5100/collect_flow_event")
BATCH_INTERVAL = float(os.environ.get("SNIF_BATCH_INTERVAL", 1.0))   # seconds to flush aggregated events
BATCH_SIZE = int(os.environ.get("SNIF_BATCH_SIZE", 200))             # max events per POST
VERBOSE = os.environ.get("SNIF_VERBOSE", "1") != "0"

# logging
log = logging.getLogger("pyshark_sniffer")
log.setLevel(logging.DEBUG if VERBOSE else logging.INFO)
ch = logging.StreamHandler()
ch.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s"))
log.addHandler(ch)

# basic flow key: src|dst|sport|dport|proto
def make_flow_key(src, dst, sport, dport, proto):
    return "|".join([str(src), str(dst), str(sport), str(dport), str(proto).upper()])

# aggregator: hold list of packet records per flow (small summary)
flows = {}
flows_lock = threading.Lock()

# queue for batched POSTs to flow collector
out_q = queue.Queue()

# minimal parser helpers
def safe_get(pkt, attr_path):
    try:
        # attr_path is like ('ip','src')
        cur = pkt
        for a in attr_path:
            cur = getattr(cur, a)
        return cur
    except Exception:
        return None

# parse flags from TCP layer into single string (e.g., "S", "SA", "R")
def tcp_flags_from_packet(pkt):
    try:
        if hasattr(pkt, 'tcp'):
            # pyshark tcp.flags_str exists in many versions
            flags = getattr(pkt.tcp, 'flags_str', None)
            if flags:
                return str(flags)
            # fallback to flags (hex) -> try tcp.flags
            flags_raw = getattr(pkt.tcp, 'flags', None)
            if flags_raw:
                # numeric string -> decode bits (not full decode but keep raw)
                return str(flags_raw)
        return ""
    except Exception:
        return ""

# convert a pyshark packet to our packet record
def pkt_to_record(pkt):
    ts = float(pkt.sniff_time.timestamp()) if hasattr(pkt, "sniff_time") else time.time()
    # default values
    src_ip = dst_ip = src_port = dst_port = proto = None
    length = None
    try:
        if hasattr(pkt, "ip"):
            src_ip = pkt.ip.src
            dst_ip = pkt.ip.dst
            proto = pkt.ip.proto
        elif hasattr(pkt, "ipv6"):
            src_ip = pkt.ipv6.src
            dst_ip = pkt.ipv6.dst
            proto = pkt.ipv6.nxt
        # transport layer
        if hasattr(pkt, "tcp"):
            src_port = pkt.tcp.srcport
            dst_port = pkt.tcp.dstport
            proto = "TCP"
        elif hasattr(pkt, "udp"):
            src_port = pkt.udp.srcport
            dst_port = pkt.udp.dstport
            proto = "UDP"
        # length fields
        # pkt.length or frame_len
        length = None
        if hasattr(pkt, "length"):
            length = int(pkt.length)
        else:
            # fallback to frame_info
            try:
                length = int(pkt.frame_info.len)
            except Exception:
                length = 0
    except Exception as e:
        log.debug("pkt_to_record parsing partial: %s", e)
    flags = tcp_flags_from_packet(pkt)
    rec = {
        "timestamp": ts,
        "bytes": length or 0,
        "packets": 1,
        "flags": flags or "",
        "src_ip": src_ip or "0.0.0.0",
        "dst_ip": dst_ip or "0.0.0.0",
        "src_port": int(src_port) if src_port else 0,
        "dst_port": int(dst_port) if dst_port else 0,
        "proto": proto or "UNK"
    }
    return rec

# ingest packet into flows map
def ingest_packet(rec):
    k = make_flow_key(rec["src_ip"], rec["dst_ip"], rec["src_port"], rec["dst_port"], rec["proto"])
    now = time.time()
    with flows_lock:
        f = flows.get(k)
        if not f:
            f = {"first_ts": rec["timestamp"], "last_ts": rec["timestamp"], "bytes": 0, "pkts": 0, "flags": set(), "events": deque()}
            flows[k] = f
        f["bytes"] += rec["bytes"]
        f["pkts"] += rec["packets"]
        f["last_ts"] = rec["timestamp"]
        if rec.get("flags"):
            # collect unique flag designators (S, A, R, F etc.)
            f["flags"].add(rec["flags"])
        # keep a small tail of timestamped samples to compute iats if needed
        f["events"].append((rec["timestamp"], rec["bytes"]))
        # cap events stored to avoid memory blow
        while len(f["events"]) > 500:
            f["events"].popleft()

# flusher: periodically convert idle flows to events and push to out_q
FLOW_TIMEOUT = float(os.environ.get("FLOW_TIMEOUT", 5.0))

def flush_idle_flows():
    while True:
        cutoff = time.time() - FLOW_TIMEOUT
        to_send = []
        with flows_lock:
            keys = list(flows.keys())
            for k in keys:
                f = flows.get(k)
                if not f:
                    continue
                if f["last_ts"] < cutoff:
                    # prepare event payload compatible with flow_collector
                    first_ts = f.get("first_ts", time.time())
                    last_ts = f.get("last_ts", first_ts)
                    flow_event = {
                        "timestamp": last_ts,
                        "bytes": float(f["bytes"]),
                        "packets": int(f["pkts"]),
                        "flags": ",".join(sorted(list(f["flags"]))),
                        "src_ip": k.split("|")[0],
                        "dst_ip": k.split("|")[1],
                        "src_port": int(k.split("|")[2]) if len(k.split("|"))>2 else 0,
                        "dst_port": int(k.split("|")[3]) if len(k.split("|"))>3 else 0,
                        "proto": k.split("|")[4] if len(k.split("|"))>4 else "UNK",
                        # metadata for flow_collector
                        "path": "",
                        "user_agent": "",
                    }
                    to_send.append(flow_event)
                    # remove flow
                    try:
                        del flows[k]
                    except Exception:
                        pass
        if to_send:
            # batch and push
            batches = [to_send[i:i+BATCH_SIZE] for i in range(0, len(to_send), BATCH_SIZE)]
            for b in batches:
                out_q.put(b)
        time.sleep(BATCH_INTERVAL)

# poster thread: takes batches from out_q and posts to FlowCollector
def poster_loop():
    session = requests.Session()
    session.headers.update({"Content-Type":"application/json"})
    while True:
        batch = out_q.get()
        try:
            r = session.post(FLOWCOLLECTOR_URL, json=batch, timeout=6.0)
            if r.ok:
                log.info("Posted %d flow events -> %s", len(batch), FLOWCOLLECTOR_URL)
            else:
                log.warning("POST returned %s; requeueing", r.status_code)
                # naive retry: requeue at end (consider shelve for persistence)
                time.sleep(1.0)
                out_q.put(batch)
        except Exception as e:
            log.warning("Failed to post batch: %s; requeueing", e)
            time.sleep(1.0)
            out_q.put(batch)
        time.sleep(0.01)

# capture loop using pyshark LiveCapture
def capture_loop(interface=CAPTURE_INTERFACE, bpf=BPF_FILTER):
    log.info("Starting capture on %s filter=%s", interface, bpf)
    # Use only_summaries False to get richer fields; use display_filter to limit more if needed
    capture = pyshark.LiveCapture(interface=interface, bpf_filter=bpf)
    try:
        for pkt in capture.sniff_continuously():
            try:
                rec = pkt_to_record(pkt)
                ingest_packet(rec)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                log.debug("packet parse error: %s", e)
    except Exception as e:
        log.exception("capture loop ended: %s", e)
    finally:
        try:
            capture.close()
        except Exception:
            pass

# CLI main
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iface", default=os.environ.get("SNIF_IFACE", CAPTURE_INTERFACE))
    parser.add_argument("--filter", default=os.environ.get("SNIF_FILTER", BPF_FILTER))
    parser.add_argument("--collector", default=os.environ.get("FLOWCOLLECTOR_URL", FLOWCOLLECTOR_URL))
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("FLOW_TIMEOUT", FLOW_TIMEOUT)))
    args = parser.parse_args()
    global CAPTURE_INTERFACE, BPF_FILTER, FLOWCOLLECTOR_URL, FLOW_TIMEOUT
    CAPTURE_INTERFACE = args.iface; BPF_FILTER = args.filter; FLOWCOLLECTOR_URL = args.collector; FLOW_TIMEOUT = args.timeout

    t_flush = threading.Thread(target=flush_idle_flows, daemon=True); t_flush.start()
    t_post = threading.Thread(target=poster_loop, daemon=True); t_post.start()

    try:
        capture_loop(interface=CAPTURE_INTERFACE, bpf=BPF_FILTER)
    except KeyboardInterrupt:
        log.info("Stopping capture (keyboard interrupt)")

if __name__ == "__main__":
    main()
