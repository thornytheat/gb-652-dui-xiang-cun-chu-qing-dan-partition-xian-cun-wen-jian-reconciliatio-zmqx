"""对象元数据归一化与快照标识。

快照标识只由对象元数据与路径规则版本决定：同一批元数据（同名文件未被覆盖）
得到同一个快照编号，元数据一旦变化就得到新编号。这样既不会重写历史批次，
也不会因为“冻结”而漏掉新差异。
"""

from __future__ import annotations

from .manifest import canonical_digest
from .modules.m2_paths.core import normalize_key

# 对象存储里常见的目录/提交标记。它们不是数据文件，不能参与文件级比对。
DIRECTORY_MARKERS = frozenset({"_SUCCESS", "_COMMIT", "_STARTED", "_FINISHED", "_$folder$"})
EMPTY_MARKERS = frozenset({"_EMPTY"})


def basename(key: str) -> str:
    return str(key).rstrip("/").rsplit("/", 1)[-1]


def object_kind(key: str) -> str:
    """返回 file / directory-marker / empty-marker。

    目录标记与空分区标记都属于“对象”，但不是可对账的数据文件；二者又必须分开，
    否则空分区会被误判成缺失分区，目录标记会被误判成缺失文件。
    """
    text = str(key)
    if text.endswith("/"):
        return "directory-marker"
    name = basename(text)
    if name in DIRECTORY_MARKERS:
        return "directory-marker"
    if name in EMPTY_MARKERS:
        return "empty-marker"
    return "file"


def prefix_of(key: str) -> str:
    parts = str(key).strip("/").split("/")
    return "/".join(parts[:-1]) if len(parts) > 1 else ""


def index_snapshot(objects) -> tuple[dict, dict, dict]:
    """把快照对象分成文件、目录标记前缀、空分区标记前缀三类，键统一归一化。

    目录标记与空分区必须分开索引：前者只说明目录存在，后者说明该分区没有数据文件。
    """
    files: dict[str, dict] = {}
    directory_prefixes: dict[str, str] = {}
    empty_prefixes: dict[str, str] = {}
    for obj in normalize_objects(objects):
        key = obj["key"]
        kind = obj.get("kind") or "file"
        if kind == "directory-marker":
            directory_prefixes[prefix_of(key)] = key
        elif kind == "empty-marker":
            empty_prefixes[prefix_of(key)] = key
        else:
            files[key] = obj
    return files, directory_prefixes, empty_prefixes


def normalize_objects(objects) -> list[dict]:
    """按归一化 key 去重，保留首次出现顺序，后出现的元数据代表核验时点的最终值。

    被覆盖的旧元数据不丢弃，记入 superseded，供复核时解释“同名文件被覆盖”。
    归一化在采集落盘后的合并阶段做，因此 `lake//a` 与 `lake/a` 会在同一快照里合并。
    """
    order: list[str] = []
    latest: dict[str, dict] = {}
    for raw in objects:
        raw_key = str(raw["key"])
        kind = raw.get("kind") or object_kind(raw_key)
        key = normalize_key(raw_key) or raw_key.strip("/")
        if key not in latest:
            order.append(key)
            superseded = list(raw.get("superseded") or [])
        else:
            previous = latest[key]
            superseded = list(previous.get("superseded") or [])
            if (previous.get("size"), previous.get("etag"), previous.get("kind")) != (
                    raw.get("size"), raw.get("etag"), kind):
                superseded.append({"size": previous.get("size"), "etag": previous.get("etag"),
                                   "kind": previous.get("kind")})
            superseded.extend(raw.get("superseded") or [])
        latest[key] = {
            "key": key,
            "raw_key": raw_key,
            "size": raw.get("size"),
            "etag": raw.get("etag"),
            "kind": kind,
            "superseded": superseded,
        }
    return [latest[key] for key in order]


def snapshot_digest(objects, rule_version: str, path_rule_version: str | None = None) -> str:
    """快照摘要包含被覆盖的旧元数据：最终值相同但覆盖历史不同也算新快照。

    这样“同名文件被覆盖过”这一事实本身也是快照身份的一部分，复核时不会丢证据。
    """
    normalized = normalize_objects(objects)
    payload = sorted(
        ({"key": o["key"], "size": o["size"], "etag": o["etag"], "kind": o["kind"],
          "superseded": o.get("superseded") or []}
         for o in normalized),
        key=lambda item: item["key"],
    )
    identity = {"rule_version": rule_version, "objects": payload}
    if path_rule_version:
        identity["path_rule_version"] = path_rule_version
    return canonical_digest(identity)


def snapshot_id(objects, rule_version: str, path_rule_version: str | None = None,
                batch_id: str | None = None) -> str:
    """快照编号包含所属批次：两个批次即使对象流一模一样，也各有各的快照。"""
    identity = {"digest": snapshot_digest(objects, rule_version, path_rule_version)}
    if batch_id:
        identity["batch_id"] = batch_id
    return "snap-" + canonical_digest(identity)[:16]
