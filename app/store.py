from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    digest TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    result TEXT NOT NULL
);

-- 批次 = 一份清单 + 一个路径规则版本。同一份清单可以随后绑定多个对象快照。
CREATE TABLE IF NOT EXISTS batches (
    batch_id TEXT PRIMARY KEY,
    manifest_digest TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    path_rule_version TEXT NOT NULL,
    status TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    latest_snapshot_id TEXT,
    UNIQUE (manifest_digest, rule_version, path_rule_version)
);

-- 快照只在整批采集完成后原子发布，发布后对象元数据不再改动。
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    digest TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    path_rule_version TEXT NOT NULL,
    object_count INTEGER NOT NULL,
    quarantine_count INTEGER NOT NULL DEFAULT 0,
    quarantine_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (batch_id, digest)
);

CREATE TABLE IF NOT EXISTS snapshot_objects (
    snapshot_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    key TEXT NOT NULL,
    size TEXT,
    etag TEXT,
    kind TEXT NOT NULL,
    superseded_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (snapshot_id, key)
);

-- 采集中断后从这里续跑；cursor 是已经消费的流位置数。
CREATE TABLE IF NOT EXISTS collections (
    collection_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    cursor INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    snapshot_id TEXT,
    quarantine_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collection_objects (
    collection_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    key TEXT NOT NULL,
    size TEXT,
    etag TEXT,
    kind TEXT NOT NULL,
    superseded_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (collection_id, key)
);

-- 对账结果按 (批次, 快照) 唯一：同一快照重试只会取回原记录，不会重复登记。
CREATE TABLE IF NOT EXISTS reconciliations (
    reconciliation_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (batch_id, snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_batch ON snapshots (batch_id, created_at);
CREATE INDEX IF NOT EXISTS idx_collections_batch ON collections (batch_id, status);
CREATE INDEX IF NOT EXISTS idx_reconciliations_batch ON reconciliations (batch_id, created_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class Store:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        """一个事务一个连接：正常退出提交，异常回滚，最后关闭连接。"""
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    # ------------------------------------------------------------------ runs
    def record(self, digest: str, run_id: str, result: dict) -> dict:
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO runs VALUES (?, ?, ?)",
                       (digest, run_id, json.dumps(result, ensure_ascii=False, sort_keys=True)))
            row = db.execute("SELECT run_id, result FROM runs WHERE digest=?", (digest,)).fetchone()
        return {"run_id": row[0], "result": json.loads(row[1])}

    def count(self) -> int:
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]

    def all(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT run_id, digest, result FROM runs ORDER BY run_id").fetchall()
        return [{"run_id": r[0], "digest": r[1], "result": json.loads(r[2])} for r in rows]

    # --------------------------------------------------------------- batches
    def create_batch(self, *, batch_id: str, manifest_digest: str, rule_version: str,
                     path_rule_version: str, manifest: dict) -> tuple[dict, bool]:
        with self.connect() as db:
            cur = db.execute(
                "INSERT OR IGNORE INTO batches "
                "(batch_id, manifest_digest, rule_version, path_rule_version, status, "
                "manifest_json, created_at) VALUES (?, ?, ?, ?, 'OPEN', ?, ?)",
                (batch_id, manifest_digest, rule_version, path_rule_version,
                 json.dumps(manifest, ensure_ascii=False, sort_keys=True), _now()),
            )
            created = cur.rowcount == 1
            row = db.execute("SELECT * FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
        return self._batch(row), created

    def get_batch(self, batch_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
        return self._batch(row) if row else None

    def find_batch(self, manifest_digest: str, rule_version: str, path_rule_version: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM batches WHERE manifest_digest=? AND rule_version=? AND path_rule_version=?",
                (manifest_digest, rule_version, path_rule_version),
            ).fetchone()
        return self._batch(row) if row else None

    def list_batches(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM batches ORDER BY created_at, rowid").fetchall()
        return [self._batch(row) for row in rows]

    @staticmethod
    def _batch(row) -> dict:
        item = dict(row)
        item["manifest"] = json.loads(item.pop("manifest_json"))
        return item

    def batch_status(self, batch_id: str) -> str:
        with self.connect() as db:
            active = db.execute(
                "SELECT 1 FROM collections WHERE batch_id=? AND status IN ('COLLECTING','INTERRUPTED') LIMIT 1",
                (batch_id,),
            ).fetchone()
            snapshot = db.execute(
                "SELECT 1 FROM snapshots WHERE batch_id=? AND status='COMPLETE' LIMIT 1", (batch_id,)
            ).fetchone()
        if active:
            return "COLLECTING"
        if snapshot:
            return "SEALED"
        return "OPEN"

    # ------------------------------------------------------------- snapshots
    def batch_snapshots(self, batch_id: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT snapshot_id, batch_id, digest, rule_version, path_rule_version, object_count, "
                "quarantine_count, status, created_at FROM snapshots WHERE batch_id=? "
                "ORDER BY created_at, rowid",
                (batch_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_snapshot(self, batch_id: str) -> dict | None:
        snapshots = self.batch_snapshots(batch_id)
        return snapshots[-1] if snapshots else None

    def get_snapshot(self, snapshot_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["quarantine"] = json.loads(item.pop("quarantine_json"))
        return item

    def snapshot_objects(self, snapshot_id: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT seq, key, size, etag, kind, superseded_json FROM snapshot_objects "
                "WHERE snapshot_id=? ORDER BY seq, key",
                (snapshot_id,),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["superseded"] = json.loads(item.pop("superseded_json"))
            out.append(item)
        return out

    # ------------------------------------------------------------ collection
    def active_collection(self, batch_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM collections WHERE batch_id=? AND status IN ('COLLECTING','INTERRUPTED') "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (batch_id,),
            ).fetchone()
        return self._collection(row) if row else None

    def create_collection(self, batch_id: str, rule_version: str) -> dict:
        collection_id = "col-" + uuid.uuid4().hex[:12]
        now = _now()
        with self.connect() as db:
            db.execute(
                "INSERT INTO collections "
                "(collection_id, batch_id, rule_version, cursor, status, quarantine_json, created_at, updated_at) "
                "VALUES (?, ?, ?, 0, 'COLLECTING', '[]', ?, ?)",
                (collection_id, batch_id, rule_version, now, now),
            )
            row = db.execute("SELECT * FROM collections WHERE collection_id=?", (collection_id,)).fetchone()
        return self._collection(row)

    def get_collection(self, collection_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM collections WHERE collection_id=?", (collection_id,)).fetchone()
        return self._collection(row) if row else None

    @staticmethod
    def _collection(row) -> dict:
        item = dict(row)
        item["quarantine"] = json.loads(item.pop("quarantine_json"))
        return item

    def collection_objects(self, collection_id: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT seq, key, size, etag, kind, superseded_json FROM collection_objects "
                "WHERE collection_id=? ORDER BY seq, key",
                (collection_id,),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["superseded"] = json.loads(item.pop("superseded_json"))
            out.append(item)
        return out

    def set_collection_status(self, collection_id: str, status: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE collections SET status=?, updated_at=? WHERE collection_id=?",
                       (status, _now(), collection_id))

    def save_progress(self, collection_id: str, records: list[dict], cursor: int,
                      status: str, quarantine: list[dict]) -> None:
        """把本次读到的对象与游标一次性写入；失败整体回滚，游标不前移。"""
        with self.connect() as db:
            session = db.execute("SELECT * FROM collections WHERE collection_id=?",
                                 (collection_id,)).fetchone()
            if not session:
                raise KeyError(collection_id)
            for record in records:
                existing = db.execute(
                    "SELECT * FROM collection_objects WHERE collection_id=? AND key=?",
                    (collection_id, record["key"]),
                ).fetchone()
                if existing:
                    superseded = json.loads(existing["superseded_json"])
                    superseded.append({"size": existing["size"], "etag": existing["etag"],
                                       "kind": existing["kind"]})
                    db.execute(
                        "UPDATE collection_objects SET size=?, etag=?, kind=?, superseded_json=? "
                        "WHERE collection_id=? AND key=?",
                        (record["size"], record["etag"], record["kind"],
                         json.dumps(superseded, ensure_ascii=False), collection_id, record["key"]),
                    )
                else:
                    db.execute(
                        "INSERT INTO collection_objects "
                        "(collection_id, seq, key, size, etag, kind, superseded_json) "
                        "VALUES (?, ?, ?, ?, ?, ?, '[]')",
                        (collection_id, record["seq"], record["key"], record["size"],
                         record["etag"], record["kind"]),
                    )
            merged = json.loads(session["quarantine_json"]) + quarantine
            db.execute(
                "UPDATE collections SET cursor=?, status=?, quarantine_json=?, updated_at=? "
                "WHERE collection_id=?",
                (cursor, status, json.dumps(merged, ensure_ascii=False), _now(), collection_id),
            )

    # --------------------------------------------------------------- publish
    def publish_snapshot(self, *, collection_id: str, batch_id: str, snapshot_id: str,
                         digest: str, rule_version: str, path_rule_version: str,
                         objects: list[dict], quarantine: list[dict]) -> dict:
        """在单个事务里发布完整快照。任何一步失败都回滚，不留下半批。

        已存在的快照编号直接复用（重试不重复登记），并把采集会话标记为已发布。
        """
        with self.connect() as db:
            existing = db.execute("SELECT 1 FROM snapshots WHERE snapshot_id=?",
                                  (snapshot_id,)).fetchone()
            if not existing:
                db.execute(
                    "INSERT INTO snapshots "
                    "(snapshot_id, batch_id, digest, rule_version, path_rule_version, object_count, "
                    "quarantine_count, quarantine_json, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'COMPLETE', ?)",
                    (snapshot_id, batch_id, digest, rule_version, path_rule_version, len(objects),
                     len(quarantine), json.dumps(quarantine, ensure_ascii=False), _now()),
                )
                db.executemany(
                    "INSERT INTO snapshot_objects "
                    "(snapshot_id, seq, key, size, etag, kind, superseded_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [(snapshot_id, obj["seq"], obj["key"], obj["size"], obj["etag"], obj["kind"],
                      json.dumps(obj.get("superseded", []), ensure_ascii=False)) for obj in objects],
                )
            db.execute(
                "UPDATE collections SET status='PUBLISHED', snapshot_id=?, updated_at=? "
                "WHERE collection_id=?",
                (snapshot_id, _now(), collection_id),
            )
            latest = db.execute(
                "SELECT snapshot_id FROM snapshots WHERE batch_id=? "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (batch_id,),
            ).fetchone()
            db.execute(
                "UPDATE batches SET status='SEALED', latest_snapshot_id=? WHERE batch_id=?",
                (latest["snapshot_id"] if latest else snapshot_id, batch_id),
            )
        return self.get_snapshot(snapshot_id)

    # ----------------------------------------------------------- reconcile
    def record_reconciliation(self, *, reconciliation_id: str, batch_id: str,
                              snapshot_id: str, rule_version: str, result: dict) -> dict:
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO reconciliations "
                "(reconciliation_id, batch_id, snapshot_id, rule_version, result_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (reconciliation_id, batch_id, snapshot_id, rule_version,
                 json.dumps(result, ensure_ascii=False, sort_keys=True), _now()),
            )
            row = db.execute("SELECT * FROM reconciliations WHERE reconciliation_id=?",
                             (reconciliation_id,)).fetchone()
        return self._reconciliation(row)

    def find_reconciliation(self, batch_id: str, snapshot_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM reconciliations WHERE batch_id=? AND snapshot_id=?",
                (batch_id, snapshot_id),
            ).fetchone()
        return self._reconciliation(row) if row else None

    def get_reconciliation(self, reconciliation_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM reconciliations WHERE reconciliation_id=?",
                             (reconciliation_id,)).fetchone()
        return self._reconciliation(row) if row else None

    def list_reconciliations(self, batch_id: str | None = None) -> list[dict]:
        with self.connect() as db:
            if batch_id:
                rows = db.execute(
                    "SELECT * FROM reconciliations WHERE batch_id=? ORDER BY created_at, rowid",
                    (batch_id,),
                ).fetchall()
            else:
                rows = db.execute("SELECT * FROM reconciliations ORDER BY created_at, rowid").fetchall()
        return [self._reconciliation(row) for row in rows]

    @staticmethod
    def _reconciliation(row) -> dict:
        item = dict(row)
        item["result"] = json.loads(item.pop("result_json"))
        return item
