SAMPLE={"manifest":[{"key":"a","size":10,"etag":"x"},{"key":"b","size":20,"etag":"y"}],"objects":[{"key":"a","size":10,"etag":"x"},{"key":"c","size":30,"etag":"z"}],"quarantine":1}
def reconcile(manifest, objects, quarantine=0):
    left={x["key"]:x for x in manifest}; right={x["key"]:x for x in objects}; common=left.keys()&right.keys()
    conflicts=sorted(k for k in common if (left[k]["size"],left[k]["etag"])!=(right[k]["size"],right[k]["etag"]))
    matched=sorted(k for k in common if k not in conflicts)
    return {"matched":matched,"missing":sorted(left.keys()-right.keys()),"orphan":sorted(right.keys()-left.keys()),"conflicts":conflicts,"quarantine_count":quarantine,"balanced":len(left)==len(matched)+len(conflicts)+len(left.keys()-right.keys())}
def run(payload):
    d=SAMPLE|payload; out=reconcile(d["manifest"],d["objects"],d.get("quarantine",0)); return {"status":"READY","input_count":len(d["manifest"]),"valid_count":len(out["matched"]),**out,"reason":"DIFF" if out["missing"] or out["orphan"] or out["conflicts"] else "OK"}
