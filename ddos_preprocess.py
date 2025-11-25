import os,json,joblib
import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score
import xgboost as xgb

ROOT=os.path.abspath(os.path.dirname(__file__))
PROC=os.path.join(ROOT,"data","processed")
csv_path=os.path.join(PROC,"processed_train.csv")

df=pd.read_csv(csv_path)
df.columns=df.columns.str.strip()

label_col=None
for c in ("label","Label","class","target"):
    if c in df.columns:label_col=c;break
if not label_col:raise SystemExit("no label col")

y=df[label_col].astype(str).str.strip().map(lambda v:1 if v.lower() not in ("0","benign","normal") else 0).values
X=df.drop(columns=[label_col])
X=X.apply(pd.to_numeric,errors="coerce").fillna(0)

features=list(X.columns)
with open(os.path.join(PROC,"feature_order.json"),"w") as f:json.dump(features,f,indent=2)

scaler=StandardScaler().fit(X.values)
joblib.dump(scaler,os.path.join(PROC,"scaler_used.save"))

Xs=scaler.transform(X.values)

Xtr,Xte,ytr,yte=train_test_split(Xs,y,test_size=0.2,random_state=42,stratify=y)

rf=RandomForestClassifier(n_estimators=300,max_depth=None,n_jobs=-1,class_weight="balanced",random_state=42)
rf.fit(Xtr,ytr)
joblib.dump(rf,os.path.join(PROC,"rf_model.save"))

try:
    dtr=xgb.DMatrix(Xtr,label=ytr)
    dte=xgb.DMatrix(Xte,label=yte)
    params={"objective":"binary:logistic","eval_metric":"auc","max_depth":6,"eta":0.15,"subsample":0.9}
    xgb_model=xgb.train(params,dtr,num_boost_round=120)
    xgb_model.save_model(os.path.join(PROC,"xgb_model.json"))
except Exception as e:
    print("xgboost error:",e)
    xgb_model=None

rf_p=rf.predict_proba(Xte)[:,1]
auc_rf=roc_auc_score(yte,rf_p)
print("RF AUC:",auc_rf)

if xgb_model:
    xgb_p=xgb_model.predict(dte)
    auc_xgb=roc_auc_score(yte,xgb_p)
    print("XGB AUC:",auc_xgb)
    auc_final=(auc_rf+(auc_xgb if xgb_model else auc_rf))/2
else:
    auc_final=auc_rf

print("FINAL AUC:",auc_final)
