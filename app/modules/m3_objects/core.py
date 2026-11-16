"""M3 对象核验：采集对象元数据、形成不可变快照、与清单逐项比对。

采集是分段、可续跑的：游标之前已经落盘的对象不再读取。只有整批采集完成、
快照在一个事务里发布成功后才算核验结果；写入失败时采集数据保留、游标保留，
重试从断点继续，不会出现半批。
"""

from app.objectmeta import index_snapshot, object_kind, prefix_of
from app.modules.m2_paths.core import normalize_key

SAMPLE={"manifest":[{"key":"a","size":"120","etag":"abc"},{"key":"b","size":"80","etag":"def-2"}],"objects":[{"key":"a","size":120,"etag":"abc"},{"key":"b","size":70,"etag":"def-2"}]}

def _text(value):
    return None if value is None else str(value)

def verify(expected, actual):
    try:
        if int(str(expected["size"]).strip()) != int(str(actual["size"]).strip()): return "SIZE_MISMATCH"
    except (TypeError, ValueError):
        return "INVALID_VALUE"
    if str(expected["etag"]) != str(actual["etag"]): return "ETAG_MISMATCH"
    return "MATCH"

def verify_all(manifest, objects):
    actual={x["key"]:x for x in objects}; out=[]
    for row in manifest:
        out.append({"key":row["key"],"status":"MISSING" if row["key"] not in actual else verify(row,actual[row["key"]])})
    return out

def collect(objects, cursor=0, max_records=None):
    """从 cursor 起读取对象流，返回这一段可落盘的记录与新的游标。

    已经消费过的位置（< cursor）不会再被访问，续跑不会重读已采对象。
    """
    total = len(objects)
    if cursor > total:
        raise ValueError("cursor 超出对象流长度：续跑必须使用同一份对象流")
    end = total if max_records is None else min(total, cursor + max_records)
    records = []
    quarantine = []
    for seq in range(cursor, end):
        raw = objects[seq]
        try:
            key = str(raw["key"])
        except (KeyError, TypeError):
            quarantine.append({"source_line": seq + 1, "reason": "BAD_COLUMNS"})
            continue
        if not key.strip():
            quarantine.append({"source_line": seq + 1, "reason": "EMPTY_VALUE"})
            continue
        kind = raw.get("kind") or object_kind(key)
        if kind not in ("file", "directory-marker", "empty-marker"):
            kind = object_kind(key)
        records.append({"seq": seq, "key": key, "size": _text(raw.get("size")),
                        "etag": _text(raw.get("etag")), "kind": kind})
    return {"records": records, "cursor": end, "done": end >= total,
            "quarantine": quarantine, "total": total}

def _prefix_of(key):
    return prefix_of(normalize_key(key))

def classify(manifest_row, files, directory_prefixes, empty_prefixes):
    """返回 (status, 命中的标记对象)。缺失时三类分开，不许混为一谈。"""
    key = normalize_key(manifest_row["key"])
    actual = files.get(key)
    if actual is not None:
        return verify(manifest_row, actual), None
    prefix = _prefix_of(key)
    if prefix in directory_prefixes:
        return "DIRECTORY_MARKER", directory_prefixes[prefix]
    if prefix in empty_prefixes:
        return "EMPTY_PARTITION", empty_prefixes[prefix]
    return "MISSING", None

def verify_snapshot(manifest, objects):
    """对现存快照对象逐项核验；缺失时区分目录标记、空分区与真正的缺失文件。"""
    files, directory_prefixes, empty_prefixes = index_snapshot(objects)
    checks = []
    for row in manifest:
        status, marker = classify(row, files, directory_prefixes, empty_prefixes)
        checks.append({"key": row["key"], "normalized_key": normalize_key(row["key"]),
                       "source_line": row.get("source_line"), "status": status,
                       "marker_key": marker})
    return checks

def run(payload):
    if "snapshot_objects" in payload:
        checks = verify_snapshot(payload.get("manifest", []), payload["snapshot_objects"])
    else:
        d = SAMPLE | payload
        checks = verify_all(d["manifest"], d["objects"])
    return {"status":"READY","input_count":len(checks),"valid_count":sum(x["status"]=="MATCH" for x in checks),"quarantine_count":sum(x["status"]!="MATCH" for x in checks),"checks":checks,"reason":"DIFF" if any(x["status"]!="MATCH" for x in checks) else "OK"}
