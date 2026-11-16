import csv, io
from app.manifest import canonical_digest, run_id

SAMPLE={"store":None,"rows":[{"key":"a","status":"MATCH","evidence":"size+etag"},{"key":"b","status":"MISSING","evidence":"manifest"}]}
FIELDS=["key","status","evidence","batch_id","snapshot_id","source_line"]

def csv_text(rows):
    out=io.StringIO(); w=csv.DictWriter(out,fieldnames=FIELDS,lineterminator="\n",extrasaction="ignore",restval=""); w.writeheader(); w.writerows(rows); return out.getvalue()

def rows_from_reconciliation(result: dict, batch_id: str = "", snapshot_id: str = "") -> list[dict]:
    """把一次对账的逐项判定摊平成证据行；批次与快照编号随每行导出。"""
    rows=[]
    for check in result.get("checks", []):
        evidence=" / ".join(str(x) for x in (check.get("manifest_size"), check.get("manifest_etag"),
                                             check.get("snapshot_size"), check.get("snapshot_etag")) if x is not None)
        rows.append({
            "batch_id": batch_id,
            "snapshot_id": snapshot_id,
            "key": check.get("key", ""),
            "source_line": check.get("source_line", ""),
            "status": check.get("status", ""),
            "evidence": evidence or (check.get("marker_key") or ""),
        })
    for key in result.get("orphan", []):
        rows.append({"batch_id": batch_id, "snapshot_id": snapshot_id, "key": key,
                     "source_line": "", "status": "ORPHAN", "evidence": "snapshot-only"})
    return rows

def run(payload):
    rows=payload.get("rows",SAMPLE["rows"]); digest=canonical_digest(rows); rid=run_id(rows)
    result={"input_count":len(rows),"valid_count":sum(x["status"]=="MATCH" for x in rows),"quarantine_count":sum(x["status"]!="MATCH" for x in rows)}
    store=payload.get("store")
    if store: rid=store.record(digest,rid,result)["run_id"]
    return {"status":"READY","run_id":rid,"digest":digest,"csv":csv_text(rows),**result,"reason":"OK"}
