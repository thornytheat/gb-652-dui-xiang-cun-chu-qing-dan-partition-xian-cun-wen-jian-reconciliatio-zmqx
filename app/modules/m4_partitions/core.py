SAMPLE={"keys":["dt=2026-11-15/hour=00/a","dt=2026-11-15/hour=01/b","dt=2026-11-15/hour=03/_EMPTY"],"expected_hours":["00","01","02","03"]}
def classify(keys, expected_hours):
    present=set(); empty=set(); duplicates=set()
    for key in keys:
        hour=next((x.split("=",1)[1] for x in key.split("/") if x.startswith("hour=")),None)
        if hour in present: duplicates.add(hour)
        if hour: present.add(hour)
        if key.endswith("/_EMPTY") and hour: empty.add(hour)
    return {"present":sorted(present),"empty":sorted(empty),"missing":sorted(set(expected_hours)-present),"duplicates":sorted(duplicates)}
def run(payload):
    d=SAMPLE|payload; out=classify(d["keys"],d["expected_hours"]); return {"status":"READY","input_count":len(d["keys"]),"valid_count":len(out["present"]),"quarantine_count":len(out["duplicates"]),**out,"reason":"GAP" if out["missing"] else "OK"}
