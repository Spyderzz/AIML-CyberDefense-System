#!/usr/bin/env python3
import os,time,json,threading,logging,argparse,requests,shelve
from collections import deque
from statistics import mean,stdev
from typing import Dict,Any,List
PREDICT_URL=os.environ.get("PREDICT_URL","http://127.0.0.1:5000/predict_flow")
ALERTS_URL=os.environ.get("ALERTS_URL","http://127.0.0.1:5000/alerts")
BLOCK_URL=os.environ.get("BLOCK_URL","http://127.0.0.1:5000/block_client")
FLOW_TIMEOUT=float(os.environ.get("FLOW_TIMEOUT",5.0))
MAX_EVENTS_PER_FLOW=int(os.environ.get("MAX_EVENTS_PER_FLOW",200))
FLUSH_INTERVAL=float(os.environ.get("FLUSH_INTERVAL",1.0))
FEATURE_ORDER_FILE=os.environ.get("FEATURE_ORDER_FILE","feature_order_corrected.json")
ALERT_THRESHOLD=float(os.environ.get("ALERT_THRESHOLD",0.5))
BLOCK_THRESHOLD=float(os.environ.get("BLOCK_THRESHOLD",0.9))
BLOCK_TTL=int(os.environ.get("BLOCK_TTL",300))
FLOWCOLLECTOR_TOKEN=os.environ.get("FLOWCOLLECTOR_TOKEN",None)
RETRY_DB=os.environ.get("FLOWCOLLECTOR_RETRY_DB","flowcollector_retry.db")
RETRY_PROCESS_INTERVAL=float(os.environ.get("RETRY_PROCESS_INTERVAL",10.0))
LOG_LEVEL=os.environ.get("LOG_LEVEL","INFO").upper()
logger=logging.getLogger("flow_collector")
logger.setLevel(LOG_LEVEL)
ch=logging.StreamHandler()
ch.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s"))
logger.addHandler(ch)
flows={}
flows_lock=threading.Lock()
def load_feature_order(path:str)->List[str]:
    try:
        with open(path,"r") as fh:
            fo=json.load(fh)
        if isinstance(fo,list) and fo:
            logger.info("Loaded feature order (%d) from %s",len(fo),path)
            return fo
        else:
            logger.warning("feature_order.json exists but format unexpected")
    except Exception as e:
        logger.warning("Could not load feature_order.json at %s: %s",path,e)
    return None
FEATURE_ORDER=load_feature_order(FEATURE_ORDER_FILE)
def safe_mean(xs):
    return float(mean(xs)) if xs else 0.0
def safe_stdev(xs):
    try:
        return float(stdev(xs)) if len(xs)>1 else 0.0
    except Exception:
        return 0.0
REQUIRED_FEATURES=[
"Flow Duration",
"Total Fwd Packets",
"Total Backward Packets",
"Flow Packets/s",
"Flow Bytes/s",
"Min Packet Length",
"Max Packet Length",
"Packet Length Mean",
"Packet Length Std",
"Packet Length Variance",
"Flow IAT Mean",
"Flow IAT Std",
"Flow IAT Max",
"Flow IAT Min",
"SYN Flag Count",
"ACK Flag Count",
"Fwd Packets/s",
"Bwd Packets/s",
]
def compute_flow_features(events:List[Dict[str,Any]],meta:Dict[str,Any])->Dict[str,float]:
    if not events:
        return {}
    timestamps=[float(e.get("timestamp",time.time())) for e in events]
    bytes_list=[float(e.get("bytes",0.0)) for e in events]
    pkts_list=[int(e.get("packets",1)) for e in events]
    flags_list=[str(e.get("flags","")).upper() for e in events]
    src_list=[e.get("src_ip") for e in events]
    dst_list=[e.get("dst_ip") for e in events]
    duration=max(timestamps)-min(timestamps) if len(timestamps)>1 else 0.0
    total_bytes=sum(bytes_list)
    total_pkts=sum(pkts_list)
    pps=float(total_pkts)/duration if duration>0 else float(total_pkts)
    bps=float(total_bytes)/duration if duration>0 else float(total_bytes)
    pkt_lengths=[]
    for b,p in zip(bytes_list,pkts_list):
        if p and p>0:
            pkt_lengths.append(b/p)
        else:
            pkt_lengths.append(b)
    timestamps_sorted=sorted(timestamps)
    iats=[timestamps_sorted[i]-timestamps_sorted[i-1] for i in range(1,len(timestamps_sorted))] if len(timestamps_sorted)>1 else []
    syn_count=sum(1 for f in flags_list if "S" in f and "A" not in f)
    ack_count=sum(1 for f in flags_list if "A" in f)
    rst_count=sum(1 for f in flags_list if "R" in f)
    fin_count=sum(1 for f in flags_list if "F" in f)
    canonical_forward=None
    if meta:
        canonical_forward=meta.get("canonical_forward") or (meta.get("src_ip"),meta.get("dst_ip"))
    if canonical_forward is None and len(events)>0:
        canonical_forward=(src_list[0],dst_list[0])
    fwd_pkts=0; bwd_pkts=0; fwd_bytes=0.0; bwd_bytes=0.0
    for e,p,b,s,d in zip(events,pkts_list,bytes_list,src_list,dst_list):
        if canonical_forward and (s,d)==tuple(canonical_forward):
            fwd_pkts+=int(p); fwd_bytes+=float(b)
        else:
            bwd_pkts+=int(p); bwd_bytes+=float(b)
    fwd_pps=float(fwd_pkts)/duration if duration>0 else float(fwd_pkts)
    bwd_pps=float(bwd_pkts)/duration if duration>0 else float(bwd_pkts)
    features={
        "Flow Duration":float(duration),
        "Total Fwd Packets":float(fwd_pkts),
        "Total Backward Packets":float(bwd_pkts),
        "Flow Packets/s":float(pps),
        "Flow Bytes/s":float(bps),
        "Min Packet Length":float(min(pkt_lengths)) if pkt_lengths else 0.0,
        "Max Packet Length":float(max(pkt_lengths)) if pkt_lengths else 0.0,
        "Packet Length Mean":float(safe_mean(pkt_lengths)),
        "Packet Length Std":float(safe_stdev(pkt_lengths)),
        "Packet Length Variance":float(safe_stdev(pkt_lengths))**2,
        "Flow IAT Mean":float(safe_mean(iats)),
        "Flow IAT Std":float(safe_stdev(iats)),
        "Flow IAT Max":float(max(iats)) if iats else 0.0,
        "Flow IAT Min":float(min(iats)) if iats else 0.0,
        "SYN Flag Count":float(syn_count),
        "ACK Flag Count":float(ack_count),
        "RST Flag Count":float(rst_count),
        "FIN Flag Count":float(fin_count),
        "Fwd Packets/s":float(fwd_pps),
        "Bwd Packets/s":float(bwd_pps),
    }
    ua=meta.get("user_agent","") if meta else ""
    features["UA_Length"]=float(len(ua))
    return features
def features_to_ordered_list(feat_map:Dict[str,float],feature_order:List[str]):
    if not feature_order:
        return [float(v) for k,v in sorted(feat_map.items())]
    return [float(feat_map.get(k,0.0)) for k in feature_order]
def make_flow_key(evt:Dict[str,Any])->str:
    src=evt.get("src_ip","0.0.0.0"); dst=evt.get("dst_ip","0.0.0.0")
    sport=str(evt.get("src_port","0")); dport=str(evt.get("dst_port","0"))
    proto=str(evt.get("proto","TCP")).upper()
    return "|".join([src,dst,sport,dport,proto])
def add_event_to_flow(evt:Dict[str,Any]):
    k=make_flow_key(evt); now=time.time()
    with flows_lock:
        f=flows.get(k)
        if f is None:
            canonical_forward=(evt.get("src_ip"),evt.get("dst_ip"))
            f={"events":deque(),"last_ts":now,"meta":{"src_ip":evt.get("src_ip"),"dst_ip":evt.get("dst_ip"),"src_port":evt.get("src_port"),"dst_port":evt.get("dst_port"),"proto":evt.get("proto"),"user_agent":evt.get("user_agent"),"path":evt.get("path"),"canonical_forward":canonical_forward}}
            flows[k]=f
        f["events"].append({"timestamp":float(evt.get("timestamp",now)),"bytes":float(evt.get("bytes",0)),"packets":int(evt.get("packets",1)),"flags":evt.get("flags",""),"src_ip":evt.get("src_ip"),"dst_ip":evt.get("dst_ip")})
        f["last_ts"]=now
        if len(f["events"])>=MAX_EVENTS_PER_FLOW:
            logger.info("Flow %s reached max events -> flushing",k)
            threading.Thread(target=flush_flow,args=(k,),daemon=True).start()
_retry_lock=threading.Lock()
def enqueue_retry(endpoint:str,payload:Dict[str,Any],meta:Dict[str,Any]=None):
    key=f"{time.time():.6f}"; rec={"endpoint":endpoint,"payload":payload,"meta":meta or {}}
    with _retry_lock:
        try:
            with shelve.open(RETRY_DB) as db:
                db[key]=rec
            logger.debug("Enqueued failed request for later retry (key=%s endpoint=%s)",key,endpoint)
        except Exception as e:
            logger.warning("Failed to enqueue retry: %s",e)
def process_retry_queue():
    while True:
        try:
            with _retry_lock:
                with shelve.open(RETRY_DB) as db:
                    keys=list(db.keys())
                    for k in keys:
                        rec=db.get(k)
                        if not rec:
                            try: del db[k]
                            except Exception: pass
                            continue
                        try:
                            hdrs={"Content-Type":"application/json"}
                            if FLOWCOLLECTOR_TOKEN: hdrs["Authorization"]=f"Bearer {FLOWCOLLECTOR_TOKEN}"
                            r=requests.post(rec["endpoint"],json=rec["payload"],headers=hdrs,timeout=6.0)
                            if r.ok:
                                logger.info("Retry successful for key=%s endpoint=%s",k,rec["endpoint"])
                                try: del db[k]
                                except Exception: pass
                            else:
                                logger.debug("Retry returned non-ok for key=%s status=%s",k,r.status_code)
                        except Exception as e:
                            logger.debug("Retry attempt failed for key=%s: %s",k,e)
        except Exception as e:
            logger.exception("process_retry_queue loop error: %s",e)
        time.sleep(RETRY_PROCESS_INTERVAL)
def flush_flow(k:str):
    with flows_lock:
        f=flows.pop(k,None)
    if not f:
        return
    events=list(f["events"]); meta=f.get("meta",{})
    try:
        feat_map=compute_flow_features(events,meta)
        if not feat_map:
            logger.warning("Flow %s computed empty features",k)
        missing=[x for x in REQUIRED_FEATURES if x not in feat_map]
        if missing:
            logger.warning("Flow %s missing required features: %s",k,missing)
        if FEATURE_ORDER and len(FEATURE_ORDER)!=len(REQUIRED_FEATURES):
            logger.info("FEATURE_ORDER length %d differs from expected %d",len(FEATURE_ORDER),len(REQUIRED_FEATURES))
        ordered=features_to_ordered_list(feat_map,FEATURE_ORDER)
        if FEATURE_ORDER and len(ordered)!=len(FEATURE_ORDER):
            if len(ordered)<len(FEATURE_ORDER):
                ordered+=[0.0]*(len(FEATURE_ORDER)-len(ordered))
        logger.debug("Ordered feature vector for flow %s: %s",k,ordered)
        payload={"features":ordered,"meta":meta}
        hdrs={"Content-Type":"application/json"}
        if FLOWCOLLECTOR_TOKEN: hdrs["Authorization"]=f"Bearer {FLOWCOLLECTOR_TOKEN}"
        try:
            r=requests.post(PREDICT_URL,json=payload,headers=hdrs,timeout=8.0)
            if not r.ok:
                logger.warning("Predict endpoint returned status=%s; enqueuing",r.status_code)
                enqueue_retry(PREDICT_URL,payload,meta)
                return
            j=r.json()
            prob=j.get("prob_attack") or j.get("prob") or j.get("flow_prob") or j.get("final_prob")
            try: prob_f=float(prob) if prob is not None else 0.0
            except Exception: prob_f=0.0
            label=j.get("label",None) or ("Attack" if prob_f>=0.5 else "Benign")
            alert_payload={"type":"ensemble_flow","time":time.time(),"flow_key":k,"prob":prob_f,"label":label,"meta":meta}
            try:
                ra=requests.post(ALERTS_URL,json=alert_payload,headers=hdrs,timeout=4.0)
                if not ra.ok:
                    logger.warning("Alerts endpoint returned %s; enqueuing",ra.status_code)
                    enqueue_retry(ALERTS_URL,alert_payload,meta)
            except Exception as e:
                logger.warning("Failed to post alert: %s; enqueuing",e)
                enqueue_retry(ALERTS_URL,alert_payload,meta)
            logger.info("Flow %s -> prob=%.4f label=%s",k,prob_f,label)
            if prob_f>=BLOCK_THRESHOLD:
                block_payload={"ip":meta.get("src_ip"),"key":k,"ttl":BLOCK_TTL,"reason":"ml_high_confidence","prob":prob_f}
                try:
                    rb=requests.post(BLOCK_URL,json=block_payload,headers=hdrs,timeout=4.0)
                    if not rb.ok:
                        logger.warning("Block endpoint returned %s; enqueuing",rb.status_code)
                        enqueue_retry(BLOCK_URL,block_payload,meta)
                    else:
                        logger.warning("Requested block for %s (prob=%.4f)",k,prob_f)
                except Exception as e:
                    logger.warning("Failed to request block: %s; enqueuing",e)
                    enqueue_retry(BLOCK_URL,block_payload,meta)
        except Exception as e:
            logger.exception("Predict POST failed: %s",e)
            enqueue_retry(PREDICT_URL,payload,meta)
            return
    except Exception as e:
        logger.exception("Failed to flush flow %s: %s",k,e)
def background_flusher():
    while True:
        try:
            cutoff = time.time() - FLOW_TIMEOUT
            to_flush = []
            with flows_lock:
                for k, f in list(flows.items()):
                    if f["last_ts"] < cutoff:
                        to_flush.append(k)
            for k in to_flush:
                try:
                    flush_flow(k)
                except Exception:
                    logger.exception("flush_flow raised for key %s", k)
        except Exception as e:
            logger.exception("background flusher error: %s", e)
        time.sleep(FLUSH_INTERVAL)
from flask import Flask,request,jsonify
flask_app=Flask("flow_collector")
@flask_app.route("/collect_flow_event",methods=["POST"])
def route_collect_event():
    payload=request.get_json(force=True,silent=True)
    if not payload:
        return jsonify({"error":"invalid json"}),400
    try:
        if isinstance(payload,list):
            for evt in payload:
                add_event_to_flow(evt)
            return jsonify({"status":"ok","ingested":len(payload)})
        else:
            add_event_to_flow(payload)
            return jsonify({"status":"ok","ingested":1})
    except Exception as e:
        logger.exception("route_collect_event error: %s",e)
        return jsonify({"error":str(e)}),500
@flask_app.route("/health",methods=["GET"])
def health():
    with flows_lock:
        n=len(flows)
    return jsonify({"status":"ok","tracked_flows":n})
def parse_args():
    p=argparse.ArgumentParser(description="FlowCollector sidecar")
    p.add_argument("--host",default=os.environ.get("HOST","0.0.0.0"))
    p.add_argument("--port",type=int,default=int(os.environ.get("PORT",5100)))
    p.add_argument("--predict-url",default=os.environ.get("PREDICT_URL",PREDICT_URL))
    p.add_argument("--alerts-url",default=os.environ.get("ALERTS_URL",ALERTS_URL))
    p.add_argument("--block-url",default=os.environ.get("BLOCK_URL",BLOCK_URL))
    p.add_argument("--feature-order",default=os.environ.get("FEATURE_ORDER_FILE",FEATURE_ORDER_FILE))
    p.add_argument("--flow-timeout",type=float,default=float(os.environ.get("FLOW_TIMEOUT",FLOW_TIMEOUT)))
    return p.parse_args()
def main():
    global PREDICT_URL,ALERTS_URL,BLOCK_URL,FEATURE_ORDER,FLOW_TIMEOUT
    args=parse_args()
    PREDICT_URL=args.predict_url; ALERTS_URL=args.alerts_url; BLOCK_URL=args.block_url
    FEATURE_ORDER=load_feature_order(args.feature_order) or FEATURE_ORDER
    FLOW_TIMEOUT=args.flow_timeout
    t_retry=threading.Thread(target=process_retry_queue,daemon=True); t_retry.start()
    t_flusher=threading.Thread(target=background_flusher,daemon=True); t_flusher.start()
    logger.info("FlowCollector starting: predict=%s alerts=%s block=%s feature_order=%s",PREDICT_URL,ALERTS_URL,BLOCK_URL,bool(FEATURE_ORDER))
    logger.info("FLOW_TIMEOUT=%s MAX_EVENTS_PER_FLOW=%s",FLOW_TIMEOUT,MAX_EVENTS_PER_FLOW)
    flask_app.run(host=args.host,port=args.port,debug=False,threaded=True)
if __name__=="__main__":
    main()
