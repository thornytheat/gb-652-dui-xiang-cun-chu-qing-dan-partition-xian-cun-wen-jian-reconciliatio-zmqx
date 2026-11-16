from fastapi import APIRouter, Body, Request
from .service import execute

router = APIRouter(tags=["M5-差异对账"])

@router.get("/reconcile")
def page(request: Request):
    service = request.app.state.batches
    batches = [service.batch_view(b) for b in service.store.list_batches()]
    batch_id = request.query_params.get("batch_id") or (batches[0]["batch_id"] if batches else None)
    data = execute()
    data["batches"] = batches
    data["batch_id"] = batch_id
    data["snapshots"] = []
    data["selected_snapshot"] = None
    data["historical"] = request.query_params.get("snapshot", "current")
    data["result"] = None
    data["reason"] = "OK"
    data["batch_missing"] = False
    if batch_id and not service.store.get_batch(batch_id):
        data["batch_missing"] = True
        return request.app.state.templates.TemplateResponse(
            request, "m5_reconcile.html", {"title": "差异对账", "data": data})
    if batch_id:
        data["snapshots"] = service.store.batch_snapshots(batch_id)
        wanted = request.query_params.get("snapshot_id")
        if wanted:
            selected = service.store.get_snapshot(wanted)
            if selected and selected["batch_id"] == batch_id:
                data["selected_snapshot"] = selected
        elif data["snapshots"]:
            index = 0 if data["historical"] == "history" else -1
            data["selected_snapshot"] = service.store.get_snapshot(data["snapshots"][index]["snapshot_id"])
        if data["selected_snapshot"]:
            batch = service.store.get_batch(batch_id)
            # 页面只是预览：已登记就取历史，未登记就现场只读计算，均不写入新记录。
            data["result"] = service.preview(batch, data["selected_snapshot"])
            data["reason"] = "DIFF" if (data["result"].get("missing") or data["result"].get("orphan")
                                        or data["result"].get("conflicts")
                                        or data["result"].get("duplicates")) else "OK"
            data["input_count"] = data["result"].get("manifest_count", 0)
            data["valid_count"] = len(data["result"].get("matched", []))
            data["quarantine_count"] = data["result"].get("quarantine_count", 0)
    return request.app.state.templates.TemplateResponse(
        request, "m5_reconcile.html", {"title": "差异对账", "data": data})

@router.post("/api/reconcile")
def api(request: Request, payload: dict = Body(default={})):
    service = request.app.state.batches
    if payload and (payload.get("batch_id") or payload.get("snapshot_id")):
        historical = payload.get("view")
        return service.reconcile(payload, historical=True if historical == "history" else None)
    return execute(payload or None)

@router.get("/api/reconcile/history")
def history(request: Request):
    service = request.app.state.batches
    batch_id = request.query_params.get("batch_id")
    service.require_batch(batch_id)
    return {"batch_id": batch_id,
            "reconciliations": service.store.list_reconciliations(batch_id),
            "snapshots": service.store.batch_snapshots(batch_id)}
