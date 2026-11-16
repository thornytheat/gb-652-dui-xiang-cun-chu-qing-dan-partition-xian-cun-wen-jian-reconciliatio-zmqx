import csv, io, json
from app.manifest import canonical_digest

SAMPLE={"text":"key,size,etag\ndt=2026-11-15/hour=00/a.parquet,120,aaa\ndt=2026-11-15/hour=01/b.parquet,80,bbb\ndt=2026-11-15/hour=01/b.parquet,81,ccc\nbad,1\n","format":"csv"}

def parse(text, fmt="csv"):
    if not text.strip(): return {"state":"empty-file","rows":[],"quarantine":[]}
    rows=[]; quarantine=[]
    if fmt=="jsonl":
        for line_no,line in enumerate(text.splitlines(),1):
            if not line.strip(): continue
            try: rows.append(json.loads(line)|{"source_line":line_no})
            except json.JSONDecodeError: quarantine.append({"source_line":line_no,"reason":"TRUNCATED"})
    else:
        reader=csv.DictReader(io.StringIO(text))
        if not reader.fieldnames: return {"state":"empty-file","rows":[],"quarantine":[]}
        reader.fieldnames=[x.lstrip("﻿") for x in reader.fieldnames]
        for line_no,row in enumerate(reader,2):
            if None in row or any(value is None for value in row.values()) or set(row)!={"key","size","etag"}: quarantine.append({"source_line":line_no,"reason":"BAD_COLUMNS"})
            else: rows.append(row|{"source_line":line_no})
    return {"state":"only-header" if not rows and not quarantine else "data","rows":rows,"quarantine":quarantine}

def manifest_digest(rows, rule_version="2026.11"):
    """清单指纹：只由清单内容与规则版本决定，重复导入得到同一个批次。"""
    entries=sorted(({"key":str(row["key"]),"size":str(row["size"]),"etag":str(row["etag"])} for row in rows),
                   key=lambda item:(item["key"],item["size"],item["etag"]))
    return canonical_digest({"rule_version":rule_version,"rows":entries})

def batch_id(manifest_digest_value, rule_version="2026.11", path_rule_version=None):
    """批次编号绑定清单、计算规则版本与路径规则版本三者。"""
    payload={"manifest":manifest_digest_value,"rule_version":rule_version}
    if path_rule_version: payload["path_rule_version"]=path_rule_version
    return "batch-"+canonical_digest(payload)[:12]

def run(payload):
    d=SAMPLE|payload; out=parse(d["text"],d.get("format","csv"))
    rule_version=d.get("rule_version","2026.11")
    path_rule_version=d.get("path_rule_version")
    digest=manifest_digest(out["rows"],rule_version)
    return {"status":"READY","input_count":len(out["rows"])+len(out["quarantine"]),"valid_count":len(out["rows"]),"quarantine_count":len(out["quarantine"]),"state":out["state"],"reason":out["quarantine"][0]["reason"] if out["quarantine"] else "OK","manifest_digest":digest,"batch_id":batch_id(digest,rule_version,path_rule_version),"rule_version":rule_version,"path_rule_version":path_rule_version,"rows":out["rows"],"quarantine":out["quarantine"]}
