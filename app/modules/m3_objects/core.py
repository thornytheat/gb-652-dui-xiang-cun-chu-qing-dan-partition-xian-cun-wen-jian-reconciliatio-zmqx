SAMPLE={"manifest":[{"key":"a","size":"120","etag":"abc"},{"key":"b","size":"80","etag":"def-2"}],"objects":[{"key":"a","size":120,"etag":"abc"},{"key":"b","size":70,"etag":"def-2"}]}
def verify(expected, actual):
    if int(expected["size"])!=int(actual["size"]): return "SIZE_MISMATCH"
    if expected["etag"]!=actual["etag"]: return "ETAG_MISMATCH"
    return "MATCH"
def verify_all(manifest, objects):
    actual={x["key"]:x for x in objects}; out=[]
    for row in manifest:
        out.append({"key":row["key"],"status":"MISSING" if row["key"] not in actual else verify(row,actual[row["key"]])})
    return out
def run(payload):
    d=SAMPLE|payload; rows=verify_all(d["manifest"],d["objects"]); return {"status":"READY","input_count":len(rows),"valid_count":sum(x["status"]=="MATCH" for x in rows),"quarantine_count":sum(x["status"]!="MATCH" for x in rows),"checks":rows,"reason":"DIFF" if any(x["status"]!="MATCH" for x in rows) else "OK"}
