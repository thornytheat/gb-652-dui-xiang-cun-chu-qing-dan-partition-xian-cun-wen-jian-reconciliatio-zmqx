from urllib.parse import unquote
SAMPLE={"paths":["/lake//dt=2026-11-15/hour=01/a%20b.parquet","lake/hour=01/dt=2026-11-15/000123.parquet","lake/_SUCCESS"]}
def normalize(path):
    parts=[unquote(x) for x in path.replace("\\","/").split("/") if x]
    fixed=[]; partitions=[]
    for part in parts:
        (partitions if "=" in part else fixed).append(part)
    return "/".join(fixed[:-1]+sorted(partitions)+fixed[-1:])
def partition_values(path):
    return {p.split("=",1)[0]:p.split("=",1)[1] for p in normalize(path).split("/") if "=" in p}
def run(payload):
    paths=payload.get("paths",SAMPLE["paths"]); out=[normalize(p) for p in paths]; return {"status":"READY","input_count":len(paths),"valid_count":len(out),"quarantine_count":0,"paths":out,"partitions":partition_values(paths[0]),"reason":"OK"}
