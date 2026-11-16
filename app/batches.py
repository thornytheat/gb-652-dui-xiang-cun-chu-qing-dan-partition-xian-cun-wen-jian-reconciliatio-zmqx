"""批次的编排：清单入库 → 绑定规则版本 → 采集对象快照 → 对账。

这个模块是唯一读写 Store 批次相关表的地方，HTTP handler 只做参数校验。
"""

from __future__ import annotations

import sqlite3

from app.errors import CollectionInterrupted, DomainError
from app.manifest import canonical_digest
from app.modules.m2_paths.core import PATH_RULE_VERSION
from app.modules.m3_objects.core import collect, verify_snapshot
from app.modules.m5_reconcile.core import summarize
from app.objectmeta import normalize_objects, snapshot_digest, snapshot_id


class BatchService:
    def __init__(self, store, settings):
        self.store = store
        self.settings = settings

    # ------------------------------------------------------------- batches
    def import_manifest(self, payload: dict) -> dict:
        from app.modules.m1_manifest.core import batch_id as derive_batch_id
        from app.modules.m1_manifest.core import manifest_digest, parse

        text = payload.get("text")
        fmt = payload.get("format", "csv")
        rule_version = payload.get("rule_version") or self.settings.rule_version
        path_rule_version = payload.get("path_rule_version") or PATH_RULE_VERSION
        if text is None:
            from app.modules.m1_manifest.core import SAMPLE
            text, fmt = SAMPLE["text"], SAMPLE.get("format", "csv")
        parsed = parse(text, fmt)
        digest = manifest_digest(parsed["rows"], rule_version)
        bid = derive_batch_id(digest, rule_version, path_rule_version)
        manifest = {
            "rows": [{"key": row["key"], "size": row["size"], "etag": row["etag"],
                      "source_line": row["source_line"]} for row in parsed["rows"]],
            "quarantine": parsed["quarantine"],
            "state": parsed["state"],
        }
        batch, created = self.store.create_batch(
            batch_id=bid, manifest_digest=digest, rule_version=rule_version,
            path_rule_version=path_rule_version, manifest=manifest,
        )
        return {
            "status": "READY",
            "batch_id": batch["batch_id"],
            "manifest_digest": digest,
            "rule_version": rule_version,
            "path_rule_version": path_rule_version,
            "created": created,
            "state": parsed["state"],
            "input_count": len(parsed["rows"]) + len(parsed["quarantine"]),
            "valid_count": len(parsed["rows"]),
            "quarantine_count": len(parsed["quarantine"]),
            "reason": parsed["quarantine"][0]["reason"] if parsed["quarantine"] else "OK",
            "rows": parsed["rows"],
            "quarantine": parsed["quarantine"],
        }

    # ---------------------------------------------------------- collection
    def collect(self, payload: dict) -> dict:
        batch = self.require_batch(payload.get("batch_id"))
        objects = payload.get("objects")
        if objects is None:
            objects = payload.get("object_stream", [])
        if not isinstance(objects, list):
            raise DomainError("INVALID_VALUE", "objects 必须是对象数组")
        max_records = payload.get("max_records")
        if max_records is not None and int(max_records) < 1:
            raise DomainError("INVALID_VALUE", "max_records 必须为正整数")
        simulate_failure = bool(payload.get("simulate_write_failure"))

        session = self._resume_or_start(batch, payload.get("collection_id"))
        cid = session["collection_id"]

        try:
            stage = collect(objects, cursor=session["cursor"], max_records=max_records)
        except ValueError as exc:
            raise DomainError("STREAM_MISMATCH", str(exc)) from exc
        records, quarantine, new_cursor = stage["records"], stage["quarantine"], stage["cursor"]

        # 先落盘本次读到的对象与游标；这一步失败整体回滚，游标停在旧断点。
        try:
            self.store.save_progress(cid, records, new_cursor,
                                     "INTERRUPTED" if not stage["done"] else "COLLECTING",
                                     quarantine)
        except sqlite3.Error as exc:
            raise CollectionInterrupted(
                "采集进度写入失败，游标未前移；可直接重试同一 collection_id",
                {"collection_id": cid, "batch_id": batch["batch_id"],
                 "cursor": session["cursor"], "total": stage["total"],
                 "collected": len(self.store.collection_objects(cid)),
                 "published": False},
            ) from exc
        stored = self.store.collection_objects(cid)

        if not stage["done"]:
            raise CollectionInterrupted(
                "采集未完成，已保存断点；用同一 collection_id 续跑，已采对象不重读，且不发布半批",
                {"collection_id": cid, "batch_id": batch["batch_id"],
                 "cursor": new_cursor, "total": stage["total"],
                 "collected": len(stored), "published": False},
            )

        # 以落盘后的对象为准形成快照：同一 key 只保留最后一次元数据，被覆盖的旧值留作证据。
        all_objects = normalize_objects(stored)
        snapshot_payload = [{"key": o["key"], "size": o["size"], "etag": o["etag"],
                             "kind": o["kind"], "superseded": o["superseded"]}
                            for o in all_objects]
        all_quarantine = self.store.get_collection(cid)["quarantine"]
        path_rule_version = batch["path_rule_version"]
        digest = snapshot_digest(snapshot_payload, batch["rule_version"], path_rule_version)
        sid = snapshot_id(snapshot_payload, batch["rule_version"], path_rule_version,
                          batch["batch_id"])

        if self.store.get_snapshot(sid) is None and simulate_failure:
            # 模拟落盘失败：采集数据与游标均已保存，但快照不发布、对账不登记。
            self.store.set_collection_status(cid, "INTERRUPTED")
            raise CollectionInterrupted(
                "快照写入失败，未发布半批；重试以同一 collection_id 从断点继续，不重复登记",
                {"collection_id": cid, "batch_id": batch["batch_id"],
                 "cursor": new_cursor, "total": stage["total"],
                 "collected": len(stored), "published": False},
            )

        try:
            self.store.publish_snapshot(
                collection_id=cid, batch_id=batch["batch_id"],
                snapshot_id=sid, digest=digest, rule_version=batch["rule_version"],
                path_rule_version=path_rule_version,
                objects=[{**o, "seq": index} for index, o in enumerate(all_objects)],
                quarantine=all_quarantine,
            )
        except sqlite3.Error as exc:
            # 发布事务整体回滚：快照、对象、对账都不会留下半批。
            self.store.set_collection_status(cid, "INTERRUPTED")
            raise CollectionInterrupted(
                "快照发布失败，已回滚为未发布状态；重试不会重复登记",
                {"collection_id": cid, "batch_id": batch["batch_id"],
                 "cursor": new_cursor, "total": stage["total"],
                 "collected": len(stored), "published": False},
            ) from exc
        checks = verify_snapshot(batch["manifest"]["rows"], snapshot_payload)
        snapshot_objects = self.store.snapshot_objects(sid)
        return {
            "status": "READY",
            "batch_id": batch["batch_id"],
            "collection_id": cid,
            "snapshot_id": sid,
            "snapshot_digest": digest,
            "rule_version": batch["rule_version"],
            "object_count": len(snapshot_payload),
            "collected_this_pass": len(records),
            "collected_total": len(stored),
            "published": True,
            "quarantine_count": len(all_quarantine),
            "checks": checks,
            "snapshot_objects": snapshot_objects,
            "reason": "DIFF" if any(c["status"] != "MATCH" for c in checks) else "OK",
        }

    def _resume_or_start(self, batch: dict, collection_id: str | None) -> dict:
        if collection_id:
            session = self.store.get_collection(collection_id)
            if not session:
                raise DomainError("UNKNOWN_COLLECTION", f"未登记的采集会话：{collection_id}")
            if session["batch_id"] != batch["batch_id"]:
                raise DomainError("BATCH_MISMATCH", "采集会话不属于该批次")
            if session["status"] == "PUBLISHED":
                raise DomainError("COLLECTION_CLOSED", "采集会话已发布，不能继续追加")
            return session
        active = self.store.active_collection(batch["batch_id"])
        if active:
            return active
        return self.store.create_collection(batch["batch_id"], batch["rule_version"])

    def preview(self, batch: dict, snapshot: dict) -> dict:
        """只读计算对账结论，不登记历史（页面展示与导出用）。"""
        stored = self.store.find_reconciliation(batch["batch_id"], snapshot["snapshot_id"])
        if stored:
            return stored["result"]
        result = summarize(batch["manifest"]["rows"],
                           self.store.snapshot_objects(snapshot["snapshot_id"]),
                           snapshot.get("quarantine_count", 0), batch["rule_version"],
                           manifest_quarantine=len(batch["manifest"]["quarantine"]))
        result["snapshot_id"] = snapshot["snapshot_id"]
        result["snapshot_digest"] = snapshot["digest"]
        result["batch_id"] = batch["batch_id"]
        return result

    def reconcile(self, payload: dict, *, historical: bool | None = None) -> dict:
        batch = self.require_batch(payload.get("batch_id"))
        explicit = payload.get("snapshot_id")
        snapshot = self.resolve_snapshot(batch["batch_id"], explicit, historical=historical)
        if snapshot is None:
            raise DomainError("SNAPSHOT_MISSING", "该批次没有可用快照，无法重算；请先完成对象采集")
        cached = self.store.find_reconciliation(batch["batch_id"], snapshot["snapshot_id"])
        if cached:
            return self._reconcile_view(batch, snapshot, cached["result"], cached["reconciliation_id"],
                                        reused=True)

        result = self.preview(batch, snapshot)
        rid = "rec-" + canonical_digest(
            {"batch": batch["batch_id"], "snapshot": snapshot["snapshot_id"],
             "rule_version": batch["rule_version"]}
        )[:16]
        stored = self.store.record_reconciliation(
            reconciliation_id=rid, batch_id=batch["batch_id"],
            snapshot_id=snapshot["snapshot_id"], rule_version=batch["rule_version"],
            result=result,
        )
        return self._reconcile_view(batch, snapshot, stored["result"], rid, reused=False)

    def _reconcile_view(self, batch, snapshot, result, reconciliation_id, *, reused):
        conflicts = result.get("conflicts", [])
        missing = result.get("missing", [])
        return {
            "status": "READY",
            "batch_id": batch["batch_id"],
            "snapshot_id": snapshot["snapshot_id"],
            "snapshot_created_at": snapshot["created_at"],
            "rule_version": batch["rule_version"],
            "reconciliation_id": reconciliation_id,
            "reused": reused,
            "input_count": result.get("manifest_count", len(batch["manifest"]["rows"])),
            "valid_count": len(result.get("matched", [])),
            "diff_count": (len(conflicts) + len(missing) + len(result.get("orphan", []))
                           + len(result.get("duplicates", []))),
            **result,
            "reason": "DIFF" if (missing or result.get("orphan") or conflicts
                                 or result.get("duplicates") or result.get("conflicts")) else "OK",
        }

    def resolve_snapshot(self, batch_id: str, snapshot_id: str | None, *,
                         historical: bool | None = None) -> dict | None:
        if snapshot_id:
            snapshot = self.store.get_snapshot(snapshot_id)
            if snapshot and snapshot["batch_id"] == batch_id:
                return snapshot
            return None
        snapshots = self.store.batch_snapshots(batch_id)
        if not snapshots:
            return None
        if historical:
            return snapshots[0]
        return snapshots[-1]

    # -------------------------------------------------------------- utils
    def require_batch(self, batch_id: str | None) -> dict:
        if not batch_id:
            raise DomainError("BATCH_REQUIRED", "缺少 batch_id：对账与采集必须绑定批次")
        batch = self.store.get_batch(batch_id)
        if not batch:
            raise DomainError("UNKNOWN_BATCH", f"未登记的批次：{batch_id}")
        return batch

    def batch_view(self, batch: dict) -> dict:
        snapshots = self.store.batch_snapshots(batch["batch_id"])
        reconciliations = self.store.list_reconciliations(batch["batch_id"])
        active = self.store.active_collection(batch["batch_id"])
        return {
            "batch_id": batch["batch_id"],
            "manifest_digest": batch["manifest_digest"],
            "rule_version": batch["rule_version"],
            "status": self.store.batch_status(batch["batch_id"]),
            "manifest_count": len(batch["manifest"]["rows"]),
            "manifest_quarantine_count": len(batch["manifest"]["quarantine"]),
            "snapshot_count": len(snapshots),
            "latest_snapshot_id": batch.get("latest_snapshot_id"),
            "latest_snapshot_at": snapshots[-1]["created_at"] if snapshots else None,
            "reconciliation_count": len(reconciliations),
            "collection": {
                "collection_id": active["collection_id"], "cursor": active["cursor"],
                "status": active["status"], "collected": len(
                    self.store.collection_objects(active["collection_id"])),
            } if active else None,
        }
