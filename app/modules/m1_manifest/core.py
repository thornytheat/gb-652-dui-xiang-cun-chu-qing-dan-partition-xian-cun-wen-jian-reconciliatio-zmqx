import csv, io, json
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
        reader=csv.DictReader(io.StringIO(text));
        if not reader.fieldnames: return {"state":"empty-file","rows":[],"quarantine":[]}
        reader.fieldnames=[x.lstrip("\ufeff") for x in reader.fieldnames]
        for line_no,row in enumerate(reader,2):
            if None in row or any(value is None for value in row.values()) or set(row)!={"key","size","etag"}: quarantine.append({"source_line":line_no,"reason":"BAD_COLUMNS"})
            else: rows.append(row|{"source_line":line_no})
    return {"state":"only-header" if not rows and not quarantine else "data","rows":rows,"quarantine":quarantine}
def run(payload):
    d=SAMPLE|payload; out=parse(d["text"],d.get("format","csv")); return {"status":"READY","input_count":len(out["rows"])+len(out["quarantine"]),"valid_count":len(out["rows"]),"quarantine_count":len(out["quarantine"]),"state":out["state"],"reason":out["quarantine"][0]["reason"] if out["quarantine"] else "OK"}
