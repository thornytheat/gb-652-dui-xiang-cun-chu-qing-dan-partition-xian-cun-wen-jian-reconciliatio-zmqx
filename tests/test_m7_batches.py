"""批次 / 快照 / 对账的组合流程测试。

覆盖四条硬约束：
1. 同一个清单可以绑定多个快照，各自独立对账，互不改写。
2. 旧批次的复核读核验时登记的大小与摘要，不重读现存文件。
3. 采集中断可从断点续跑；写入失败不发布半批，重试不重复登记。
4. 缺失必须分三类：目录标记、空分区、缺失文件。
"""

from app.modules.m2_paths.core import PATH_RULE_VERSION

MANIFEST = """key,size,etag
dt=2026-11-15/hour=00/a.parquet,120,aaa
dt=2026-11-15/hour=01/b.parquet,80,bbb
dt=2026-11-15/hour=02/c.parquet,40,ccc
dt=2026-11-15/hour=03/d.parquet,20,ddd
"""

FIRST_SNAPSHOT = [
    {"key": "dt=2026-11-15/hour=00/a.parquet", "size": 120, "etag": "aaa"},
    {"key": "dt=2026-11-15/hour=01/b.parquet", "size": 80, "etag": "bbb"},
    {"key": "dt=2026-11-15/hour=01/_SUCCESS", "size": 0, "etag": "m"},
    {"key": "dt=2026-11-15/hour=02/_EMPTY", "size": 0, "etag": "e"},
    {"key": "dt=2026-11-15/hour=03/_EMPTY", "size": 0, "etag": "e"},
]


def import_batch(client, text=MANIFEST):
    response = client.post("/api/manifests/import", json={"text": text, "format": "csv"})
    assert response.status_code == 200
    return response.json()


def collect(client, batch_id, objects, **extra):
    return client.post("/api/objects/verify", json={"batch_id": batch_id, "objects": objects, **extra})


def test_import_binds_manifest_and_rule_version(client):
    first = import_batch(client)
    assert first["created"] is True
    assert first["batch_id"].startswith("batch-")
    assert first["rule_version"] == "2026.11"
    assert first["path_rule_version"] == PATH_RULE_VERSION
    again = import_batch(client)
    assert again["batch_id"] == first["batch_id"]
    assert again["created"] is False
    # 同一清单换一个规则版本就是另一个批次
    other = client.post("/api/manifests/import", json={"text": MANIFEST, "rule_version": "2027.01"}).json()
    assert other["batch_id"] != first["batch_id"]

    batches = client.get("/api/batches").json()["batches"]
    assert len(batches) == 2
    bound = next(b for b in batches if b["batch_id"] == first["batch_id"])
    assert bound["rule_version"] == "2026.11"


def test_missing_snapshot_rejects_recompute(client):
    batch = import_batch(client)
    response = client.post("/api/reconcile", json={"batch_id": batch["batch_id"]})
    assert response.status_code == 422
    assert response.json()["error"] == "SNAPSHOT_MISSING"
    unknown = client.post("/api/reconcile", json={"batch_id": "batch-000000000000"})
    assert unknown.status_code == 422
    assert unknown.json()["error"] == "UNKNOWN_BATCH"
    # 空负载只是样例演示，不构成任何真实批次对账，也不登记历史
    demo = client.post("/api/reconcile", json={})
    assert demo.status_code == 200
    assert demo.json().get("batch_id") is None
    assert client.get("/api/reconcile/history").status_code == 422


def test_snapshot_distinguishes_markers_empty_and_missing(client):
    batch = import_batch(client)
    response = collect(client, batch["batch_id"], FIRST_SNAPSHOT)
    assert response.status_code == 200
    body = response.json()
    assert body["published"] is True
    statuses = {check["key"]: check["status"] for check in body["checks"]}
    assert statuses["dt=2026-11-15/hour=00/a.parquet"] == "MATCH"
    # hour=02 只有空分区标记：不是匹配，也不是缺失文件
    assert statuses["dt=2026-11-15/hour=02/c.parquet"] == "EMPTY_PARTITION"
    assert statuses["dt=2026-11-15/hour=03/d.parquet"] == "EMPTY_PARTITION"

    result = client.post("/api/reconcile", json={"batch_id": batch["batch_id"]}).json()
    assert result["empty_partitions"] == ["dt=2026-11-15/hour=02/c.parquet",
                                          "dt=2026-11-15/hour=03/d.parquet"]
    assert result["missing"] == []
    assert result["directory_markers"] == []
    assert result["balanced"] is True


def test_directory_marker_is_not_a_missing_file(client):
    batch = import_batch(client)
    objects = [
        {"key": "dt=2026-11-15/hour=00/a.parquet", "size": 120, "etag": "aaa"},
        {"key": "dt=2026-11-15/hour=00/_SUCCESS", "size": 0, "etag": "m"},
    ]
    assert collect(client, batch["batch_id"], objects).status_code == 200
    result = client.post("/api/reconcile", json={"batch_id": batch["batch_id"]}).json()
    assert "dt=2026-11-15/hour=00/a.parquet" in result["matched"]
    assert "dt=2026-11-15/hour=01/b.parquet" in result["missing"]
    assert result["directory_markers"] == []
    assert "dt=2026-11-15/hour=00/_SUCCESS" not in result["missing"]


def test_same_manifest_two_snapshots_keep_history(client):
    batch = import_batch(client)
    first = collect(client, batch["batch_id"], FIRST_SNAPSHOT).json()
    assert first["snapshot_id"].startswith("snap-")

    # 同名文件被覆盖：第二次采集得到新快照，旧快照仍保留原大小与摘要
    second_stream = [
        {"key": "dt=2026-11-15/hour=00/a.parquet", "size": 999, "etag": "new"},
        {"key": "dt=2026-11-15/hour=01/b.parquet", "size": 80, "etag": "bbb"},
    ]
    second = collect(client, batch["batch_id"], second_stream).json()
    assert second["snapshot_id"] != first["snapshot_id"]

    detail = client.get(f"/api/batches/{batch['batch_id']}").json()
    assert [s["snapshot_id"] for s in detail["snapshots"]] == [
        first["snapshot_id"], second["snapshot_id"]]

    old = client.post("/api/reconcile", json={"batch_id": batch["batch_id"],
                                              "snapshot_id": first["snapshot_id"]}).json()
    new = client.post("/api/reconcile", json={"batch_id": batch["batch_id"],
                                              "snapshot_id": second["snapshot_id"]}).json()
    # 旧批次复核读的是核验时的大小，不受现存文件影响
    assert old["conflicts"] == []
    assert old["matched"] == ["dt=2026-11-15/hour=00/a.parquet",
                              "dt=2026-11-15/hour=01/b.parquet"]
    # 新快照才反映覆盖后的差异
    assert new["conflicts"] == ["dt=2026-11-15/hour=00/a.parquet"]
    old_checks = [c for c in old["checks"] if c["key"].endswith("a.parquet")][0]
    assert old_checks["snapshot_size"] == "120"
    new_checks = [c for c in new["checks"] if c["key"].endswith("a.parquet")][0]
    assert new_checks["snapshot_size"] == "999"


def test_interrupted_collection_resumes_without_reread(client):
    batch = import_batch(client)
    stream = list(FIRST_SNAPSHOT)
    first = collect(client, batch["batch_id"], stream, max_records=2)
    assert first.status_code == 409
    body = first.json()
    assert body["error"] == "COLLECTION_INTERRUPTED"
    assert body["cursor"] == 2 and body["published"] is False
    assert client.get(f"/api/batches/{batch['batch_id']}").json()["snapshots"] == []

    collection_id = body["collection_id"]
    second = collect(client, batch["batch_id"], stream, max_records=2, collection_id=collection_id)
    assert second.status_code == 409
    assert second.json()["cursor"] == 4
    assert second.json()["collected"] == 4

    third = collect(client, batch["batch_id"], stream, collection_id=collection_id).json()
    assert third["published"] is True
    assert third["collected_this_pass"] == 1
    assert third["object_count"] == 5

    # 续跑不会再读已采对象：用同一份流从头重放也只能得到同一快照
    replay = collect(client, batch["batch_id"], stream).json()
    assert replay["snapshot_id"] == third["snapshot_id"]
    detail = client.get(f"/api/batches/{batch['batch_id']}").json()
    assert len(detail["snapshots"]) == 1


def test_write_failure_publishes_nothing_and_retry_is_idempotent(client):
    batch = import_batch(client)
    failed = collect(client, batch["batch_id"], FIRST_SNAPSHOT, simulate_write_failure=True)
    assert failed.status_code == 409
    body = failed.json()
    assert body["published"] is False
    assert client.get(f"/api/batches/{batch['batch_id']}").json()["snapshots"] == []
    history = client.get("/api/reconcile/history", params={"batch_id": batch["batch_id"]}).json()
    assert history["reconciliations"] == []

    retry = collect(client, batch["batch_id"], FIRST_SNAPSHOT,
                    collection_id=body["collection_id"]).json()
    assert retry["published"] is True
    assert retry["collected_this_pass"] == 0  # 断点之后已无新对象
    assert retry["collected_total"] == 5

    again = collect(client, batch["batch_id"], FIRST_SNAPSHOT,
                    collection_id=body["collection_id"])
    assert again.status_code == 422
    assert again.json()["error"] == "COLLECTION_CLOSED"

    detail = client.get(f"/api/batches/{batch['batch_id']}").json()
    assert len(detail["snapshots"]) == 1


def test_reconcile_is_registered_once_per_snapshot(client):
    batch = import_batch(client)
    collect(client, batch["batch_id"], FIRST_SNAPSHOT)
    first = client.post("/api/reconcile", json={"batch_id": batch["batch_id"]}).json()
    second = client.post("/api/reconcile", json={"batch_id": batch["batch_id"]}).json()
    assert first["reconciliation_id"] == second["reconciliation_id"]
    assert first["reused"] is False and second["reused"] is True
    history = client.get("/api/reconcile/history", params={"batch_id": batch["batch_id"]}).json()
    assert len(history["reconciliations"]) == 1


def test_export_selected_batch_and_snapshot(client):
    batch = import_batch(client)
    snapshot = collect(client, batch["batch_id"], FIRST_SNAPSHOT).json()
    response = client.get("/api/export/differences.csv",
                          params={"batch_id": batch["batch_id"],
                                  "snapshot_id": snapshot["snapshot_id"]})
    assert response.status_code == 200
    body = response.text
    assert body.startswith("key,status,evidence")
    assert batch["batch_id"] in body
    assert snapshot["snapshot_id"] in body
    assert "EMPTY_PARTITION" in body

    missing = client.get("/api/export/differences.csv", params={"batch_id": "batch-000000000000"})
    assert missing.status_code == 422


def test_two_batches_with_same_objects_get_separate_snapshots(client):
    first = import_batch(client)
    second = import_batch(client, MANIFEST + "dt=2026-11-15/hour=04/e.parquet,10,eee\n")
    a = collect(client, first["batch_id"], FIRST_SNAPSHOT)
    b = collect(client, second["batch_id"], FIRST_SNAPSHOT)
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()["snapshot_id"] != b.json()["snapshot_id"]
    # 两个批次各自能取到自己的快照，不会互相挡住
    assert client.post("/api/reconcile", json={"batch_id": second["batch_id"]}).status_code == 200
    assert client.get("/api/export/differences.csv",
                      params={"batch_id": second["batch_id"]}).status_code == 200


def test_overwritten_object_keeps_superseded_evidence(client):
    batch = import_batch(client)
    stream = [
        {"key": "dt=2026-11-15/hour=00/a.parquet", "size": 120, "etag": "aaa"},
        {"key": "dt=2026-11-15/hour=00/a.parquet", "size": 121, "etag": "bbb"},
    ]
    body = collect(client, batch["batch_id"], stream).json()
    assert body["object_count"] == 1
    stored = client.get(f"/api/batches/{batch['batch_id']}").json()
    assert stored["snapshots"][0]["object_count"] == 1
    check = client.post("/api/reconcile", json={"batch_id": batch["batch_id"]}).json()["checks"][0]
    assert check["snapshot_size"] == "121"
    # 旧值作为证据保留在快照对象里
    object_row = body["snapshot_objects"][0]
    assert object_row["superseded"] == [{"size": "120", "etag": "aaa", "kind": "file"}]


def test_export_and_page_are_read_only(client):
    batch = import_batch(client)
    collect(client, batch["batch_id"], FIRST_SNAPSHOT)
    before = client.get("/api/reconcile/history", params={"batch_id": batch["batch_id"]}).json()
    assert before["reconciliations"] == []

    assert client.get(f"/reconcile?batch_id={batch['batch_id']}").status_code == 200
    assert client.get("/api/export/differences.csv", params={"batch_id": batch["batch_id"]}).status_code == 200
    after = client.get("/api/reconcile/history", params={"batch_id": batch["batch_id"]}).json()
    assert after["reconciliations"] == []

    # 只有显式运行对账才登记一条
    client.post("/api/reconcile", json={"batch_id": batch["batch_id"]})
    assert len(client.get("/api/reconcile/history",
                          params={"batch_id": batch["batch_id"]}).json()["reconciliations"]) == 1


def test_reconcile_page_selects_history_or_current(client):
    batch = import_batch(client)
    collect(client, batch["batch_id"], FIRST_SNAPSHOT)
    second_stream = [{"key": "dt=2026-11-15/hour=00/a.parquet", "size": 999, "etag": "new"}]
    second = collect(client, batch["batch_id"], second_stream).json()

    current = client.get(f"/reconcile?batch_id={batch['batch_id']}")
    assert current.status_code == 200
    assert second["snapshot_id"] in current.text
    assert "快照" in current.text

    history = client.get(f"/reconcile?batch_id={batch['batch_id']}&snapshot=history")
    assert history.status_code == 200
    assert "历史快照" in history.text

    unknown = client.get("/reconcile?batch_id=batch-000000000000")
    assert unknown.status_code == 200
    assert "批次不存在" in unknown.text
