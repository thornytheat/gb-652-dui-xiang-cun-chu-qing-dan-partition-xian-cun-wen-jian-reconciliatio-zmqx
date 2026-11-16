import csv, io
from app.manifest import canonical_digest, run_id
SAMPLE={"store":None,"rows":[{"key":"a","status":"MATCH","evidence":"size+etag"},{"key":"b","status":"MISSING","evidence":"manifest"}]}
def csv_text(rows):
    out=io.StringIO(); w=csv.DictWriter(out,fieldnames=["key","status","evidence"],lineterminator="\n"); w.writeheader(); w.writerows(rows); return out.getvalue()
def run(payload):
    rows=payload.get("rows",SAMPLE["rows"]); digest=canonical_digest(rows); rid=run_id(rows); result={"input_count":len(rows),"valid_count":sum(x["status"]=="MATCH" for x in rows),"quarantine_count":sum(x["status"]!="MATCH" for x in rows)}; store=payload.get("store")
    if store: rid=store.record(digest,rid,result)["run_id"]
    return {"status":"READY","run_id":rid,"digest":digest,"csv":csv_text(rows),**result,"reason":"OK"}
