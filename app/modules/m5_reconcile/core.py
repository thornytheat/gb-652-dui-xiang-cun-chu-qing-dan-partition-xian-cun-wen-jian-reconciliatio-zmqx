"""M5 差异对账。

对账的一端是批次清单，另一端是批次绑定的对象快照（不是“当前目录”）。
同一个批次可以按不同快照各开一次对账，历史结果不改写：复核旧批次时读的就是
当时快照里登记的大小与摘要。
"""

from app.modules.m2_paths.core import normalize_key
from app.modules.m3_objects.core import classify
from app.objectmeta import index_snapshot, normalize_objects

SAMPLE={"manifest":[{"key":"a","size":10,"etag":"x"},{"key":"b","size":20,"etag":"y"}],"objects":[{"key":"a","size":10,"etag":"x"},{"key":"c","size":30,"etag":"z"}],"quarantine":1}


def reconcile(manifest, objects, quarantine=0):
    left={x["key"]:x for x in manifest}
    right={x["key"]:x for x in objects}
    common=left.keys()&right.keys()
    conflicts=sorted(k for k in common if (left[k].get("size"),left[k].get("etag"))!=(right[k].get("size"),right[k].get("etag")))
    matched=sorted(k for k in common if k not in conflicts)
    return {"matched":matched,"missing":sorted(left.keys()-right.keys()),"orphan":sorted(right.keys()-left.keys()),"conflicts":conflicts,"quarantine_count":quarantine,"balanced":len(left)==len(matched)+len(conflicts)+len(left.keys()-right.keys())}


def summarize(manifest, snapshot_objects, quarantine=0, rule_version="2026.11",
              manifest_quarantine=0):
    """按快照元数据逐行对账；缺失分成目录标记、空分区、缺失文件三类。

    守恒：清单行数 = 匹配 + 冲突 + 缺失文件 + 目录标记 + 空分区 + 重复行。
    quarantine 是采集阶段隔离的对象数，manifest_quarantine 是清单采信阶段的隔离数，
    两者都单独登记，不并入本阶段的分类计数。
    """
    objects = normalize_objects(snapshot_objects)
    files, directory_prefixes, empty_prefixes = index_snapshot(objects)

    groups: dict[str, list[dict]] = {}
    for row in manifest:
        groups.setdefault(normalize_key(row["key"]), []).append(row)

    checks = []
    for key, rows in groups.items():
        first, extras = rows[0], rows[1:]
        actual = files.get(key)
        status, marker = classify(first, files, directory_prefixes, empty_prefixes)
        checks.append({
            "key": first["key"], "normalized_key": key,
            "source_line": first.get("source_line"),
            "status": status,
            "manifest_size": first.get("size"), "manifest_etag": first.get("etag"),
            "snapshot_size": actual.get("size") if actual else None,
            "snapshot_etag": actual.get("etag") if actual else None,
            "marker_key": marker,
            "reason": status if status != "MATCH" else "OK",
        })
        for extra in extras:
            same = (str(extra.get("size")), str(extra.get("etag"))) == (
                str(first.get("size")), str(first.get("etag")))
            extra_status = "DUPLICATE_ROW" if same else "DUPLICATE_CONFLICT"
            checks.append({
                "key": extra["key"], "normalized_key": key,
                "source_line": extra.get("source_line"),
                "status": extra_status,
                "manifest_size": extra.get("size"), "manifest_etag": extra.get("etag"),
                "snapshot_size": actual.get("size") if actual else None,
                "snapshot_etag": actual.get("etag") if actual else None,
                "marker_key": None,
                "reason": extra_status,
            })

    def keys_of(status):
        return [c["key"] for c in checks if c["status"] == status]

    listed = set(groups)
    orphan = sorted(key for key in files if key not in listed)
    duplicate_count = len(keys_of("DUPLICATE_ROW")) + len(keys_of("DUPLICATE_CONFLICT"))
    buckets = (len(keys_of("MATCH")) + len(keys_of("SIZE_MISMATCH"))
               + len(keys_of("ETAG_MISMATCH")) + len(keys_of("INVALID_VALUE"))
               + len(keys_of("MISSING")) + len(keys_of("DIRECTORY_MARKER"))
               + len(keys_of("EMPTY_PARTITION")) + duplicate_count)
    result = {
        "checks": checks,
        "matched": keys_of("MATCH"),
        "conflicts": sorted(keys_of("SIZE_MISMATCH") + keys_of("ETAG_MISMATCH") + keys_of("INVALID_VALUE")),
        "missing": sorted(keys_of("MISSING")),
        "directory_markers": sorted(keys_of("DIRECTORY_MARKER")),
        "empty_partitions": sorted(keys_of("EMPTY_PARTITION")),
        "duplicates": sorted(keys_of("DUPLICATE_ROW") + keys_of("DUPLICATE_CONFLICT")),
        "duplicate_conflicts": sorted(keys_of("DUPLICATE_CONFLICT")),
        "duplicate_rows": sorted(keys_of("DUPLICATE_ROW")),
        "orphan": orphan,
        # quarantine 是采集阶段被隔离的对象数，不占清单行；单独登记避免混淆两类计数。
        "collection_quarantine_count": quarantine,
        "manifest_quarantine_count": manifest_quarantine,
        "quarantine_count": len(checks) - len(keys_of("MATCH")),
        "object_count": len(objects),
        "file_count": len(files),
        "manifest_count": len(checks),
        "unique_manifest_count": len(groups),
        "duplicate_count": duplicate_count,
        # 守恒式：每一行清单都必须落进且只落进一个分类桶。
        "balanced": buckets == len(checks),
        "rule_version": rule_version,
    }
    return result


def run(payload):
    d=SAMPLE|payload
    if "snapshot_objects" in payload:
        out=summarize(payload.get("manifest",[]),payload["snapshot_objects"],payload.get("quarantine",0),payload.get("rule_version","2026.11"))
        reason="DIFF" if out["missing"] or out["orphan"] or out["conflicts"] or out["duplicates"] else "OK"
        return {"status":"READY","reason":reason,"input_count":out["manifest_count"],"valid_count":len(out["matched"]),**out}
    out=reconcile(d["manifest"],d["objects"],d.get("quarantine",0))
    return {"status":"READY","input_count":len(d["manifest"]),"valid_count":len(out["matched"]),**out,"reason":"DIFF" if out["missing"] or out["orphan"] or out["conflicts"] else "OK"}
