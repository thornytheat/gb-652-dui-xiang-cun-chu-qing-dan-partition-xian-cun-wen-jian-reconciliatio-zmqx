from app.objectmeta import object_kind

SAMPLE={"keys":["dt=2026-11-15/hour=00/a","dt=2026-11-15/hour=01/b","dt=2026-11-15/hour=03/_EMPTY"],"expected_hours":["00","01","02","03"]}

def _hour(key):
    return next((x.split("=",1)[1] for x in key.split("/") if x.startswith("hour=")),None)

def classify(keys, expected_hours):
    """按小时分区判定：数据文件、空分区标记、目录标记分开计。

    空分区（只有 `_EMPTY`）不等于缺失，也不等于有数据；目录标记（`_SUCCESS` 等）不占分区。
    """
    present=set(); empty=set(); markers=set(); duplicates=set(); seen=set()
    for key in keys:
        hour=_hour(key)
        kind=object_kind(key)
        if kind=="directory-marker":
            if hour: markers.add(hour)
            continue
        if kind=="empty-marker":
            if hour: empty.add(hour)
            continue
        if hour and hour in seen: duplicates.add(hour)
        if hour: seen.add(hour)
    present=seen
    # 空分区已被标记覆盖，不再算缺失；目录标记不算数据也不覆盖缺失。
    missing=sorted(set(expected_hours)-present-empty)
    return {"present":sorted(present),"empty":sorted(empty),"markers":sorted(markers),"missing":missing,"duplicates":sorted(duplicates)}

def run(payload):
    d=SAMPLE|payload; out=classify(d["keys"],d["expected_hours"])
    return {"status":"READY","input_count":len(d["keys"]),"valid_count":len(out["present"]),"quarantine_count":len(out["duplicates"]),"reason":"GAP" if out["missing"] else "OK",**out}
