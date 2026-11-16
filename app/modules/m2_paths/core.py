from urllib.parse import unquote

# 路径归一化规则的版本号。批次绑定它：规则升级后旧批次仍能按原规则复算。
PATH_RULE_VERSION = "path-2026.11"

SAMPLE={"paths":["/lake//dt=2026-11-15/hour=01/a%20b.parquet","lake/hour=01/dt=2026-11-15/000123.parquet","lake/_SUCCESS"]}

def normalize(path):
    parts=[unquote(x) for x in path.replace("\\","/").split("/") if x]
    fixed=[]; partitions=[]
    for part in parts:
        (partitions if "=" in part else fixed).append(part)
    return "/".join(fixed[:-1]+sorted(partitions)+fixed[-1:])

def normalize_key(path):
    """比对用的键：归一化后的大小写敏感、去首尾斜杠的完整路径。"""
    return normalize(path).strip("/")

def partition_values(path):
    return {p.split("=",1)[0]:p.split("=",1)[1] for p in normalize(path).split("/") if "=" in p}

def run(payload):
    paths=payload.get("paths",SAMPLE["paths"]); out=[normalize(p) for p in paths]
    return {"status":"READY","path_rule_version":PATH_RULE_VERSION,"input_count":len(paths),"valid_count":len(out),"quarantine_count":0,"paths":out,"keys":[normalize_key(p) for p in paths],"partitions":partition_values(paths[0]),"reason":"OK"}
