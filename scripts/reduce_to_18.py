# scripts/reduce_to_18.py
"""
Reduce processed CICIDS data to the minimal 18-feature set, keep order, save reduced train/test CSVs.
Usage:
  python scripts/reduce_to_18.py --processed_dir data/processed
or (if you only have raw csvs)
  python scripts/reduce_to_18.py --raw_dir path/to/CICIDS_csvs --out_dir data/processed
"""
import os
import argparse
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split

FEATURE_ORDER = [
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
    "Bwd Packets/s"
]

def try_load_processed(pd_dir):
    train_p = os.path.join(pd_dir, "processed_train.csv")
    test_p = os.path.join(pd_dir, "processed_test.csv")
    if os.path.exists(train_p) and os.path.exists(test_p):
        print("Loading existing processed CSVs:", train_p, test_p)
        train = pd.read_csv(train_p)
        test = pd.read_csv(test_p)
        return train, test
    return None, None

def load_raw_and_select(raw_dir):
    files = []
    for root,_,fnames in os.walk(raw_dir):
        for f in fnames:
            if f.lower().endswith(".csv"):
                files.append(os.path.join(root,f))
    if not files:
        raise FileNotFoundError("No CSV found in raw_dir: "+raw_dir)
    print("Found raw CSVs:", len(files))
    dfs = []
    for f in files:
        try:
            dfs.append(pd.read_csv(f))
        except Exception as e:
            print("Skipping", f, e)
    df = pd.concat(dfs, ignore_index=True)
    return df

def extract_columns(df):
    cols_map = {c.strip(): c for c in df.columns}
    out = {}
    lc_map = {c.lower(): c for c in df.columns}
    for feat in FEATURE_ORDER + ["label"]:
        if feat in cols_map:
            out[feat] = cols_map[feat]
        else:
            k = feat.lower()
            if k in lc_map:
                out[feat] = lc_map[k]
            else:
                candidates = [c for c in df.columns if k.replace(" ","") in c.lower().replace(" ","")]
                if candidates:
                    out[feat] = candidates[0]
                else:
                    raise KeyError(f"Feature '{feat}' not found in dataset columns. Available columns sample: {list(df.columns)[:20]}")
    # build reduced DF
    reduced = df[[out[f] for f in FEATURE_ORDER] + [out["label"]]].copy()
    reduced.columns = FEATURE_ORDER + ["label"]
    return reduced

def main(args):
    os.makedirs(args.out_dir, exist_ok=True)
    train, test = try_load_processed(args.processed_dir or args.out_dir)
    if train is None:
        if not args.raw_dir:
            raise RuntimeError("No processed CSVs found and no raw_dir provided.")
        df = load_raw_and_select(args.raw_dir)
        label_col = None
        for c in df.columns:
            if 'label' in c.lower():
                label_col = c
                break
        if label_col is None:
            raise KeyError("No label column found in raw data.")
        df = df.rename(columns={label_col: "label"})
        df = df[df['label'].notna()]
        reduced = extract_columns(df)
        # split
        X = reduced.drop(columns=["label"])
        y = reduced["label"]
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
        train_df = X_tr.copy(); train_df["label"] = y_tr.values
        test_df = X_te.copy(); test_df["label"] = y_te.values
    else:
        train_df = extract_columns(train)
        test_df = extract_columns(test)
    # fill NaNs with medians
    for df in (train_df, test_df):
        med = df[FEATURE_ORDER].median()
        df[FEATURE_ORDER] = df[FEATURE_ORDER].fillna(med).astype(float)
    train_df.to_csv(os.path.join(args.out_dir, "processed_reduced_train.csv"), index=False)
    test_df.to_csv(os.path.join(args.out_dir, "processed_reduced_test.csv"), index=False)
    print("Saved reduced processed CSVs to", args.out_dir)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--raw_dir", help="raw CICIDS CSV folder (only if processed CSVs don't exist)")
    p.add_argument("--processed_dir", default="data/processed", help="where processed_train.csv might already exist")
    p.add_argument("--out_dir", default="data/processed", help="output folder for reduced CSVs")
    args = p.parse_args()
    main(args)
