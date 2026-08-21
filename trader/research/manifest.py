from pathlib import Path
import hashlib,json,platform,subprocess,sys
from importlib.metadata import version,PackageNotFoundError
import pandas as pd

def config_hash(cfg):return hashlib.sha256(json.dumps(cfg,sort_keys=True,default=str).encode()).hexdigest()
def git_commit(root):
    try:return subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip()
    except Exception:return "UNKNOWN"
def write_manifest(path:Path,readiness,cfg,period,execution_model,run_id):
    deps={}
    for name in ("pandas","numpy","scipy","pyarrow","pydantic","SQLAlchemy"):
        try:deps[name]=version(name)
        except PackageNotFoundError:deps[name]="missing"
    payload={"run_id":run_id,"git_commit":git_commit(path.parents[1]),"dataset_version":readiness.dataset_version,"dataset_hash":readiness.dataset_hash,"config_hash":config_hash(cfg),"period":period,"execution_model":execution_model,"timestamp":pd.Timestamp.now(tz="Asia/Taipei").isoformat(),"python_version":platform.python_version(),"dependency_versions":deps};path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(payload,indent=2),encoding="utf-8");return payload
