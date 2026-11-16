from fastapi import APIRouter, Request
from fastapi.responses import Response
from .service import execute
from .core import csv_text, rows_from_reconciliation

router = APIRouter(tags=["M6-批次导出"])


def _batch_rows(service, batch_id: str, snapshot_id: str | None) -> list[dict]:
    """导出是只读动作：取已登记对账或现场计算，都不写入历史。"""
    batch = service.require_batch(batch_id)
    snapshot = service.resolve_snapshot(batch_id, snapshot_id, historical=None)
    if snapshot is None:
        from app.errors import DomainError
        raise DomainError("SNAPSHOT_MISSING", "该批次没有可用快照，无法导出；请先完成对象采集")
    result = service.preview(batch, snapshot)
    return rows_from_reconciliation(result, batch_id, snapshot["snapshot_id"])


@router.get("/runs")
def page(request: Request):
    service = request.app.state.batches
    batches = [service.batch_view(b) for b in service.store.list_batches()]
    batch_id = request.query_params.get("batch_id") or (batches[0]["batch_id"] if batches else None)
    data = execute({"store": request.app.state.store})
    data["batches"] = batches
    data["batch_id"] = batch_id
    data["snapshots"] = service.store.batch_snapshots(batch_id) if batch_id else []
    data["reconciliations"] = service.store.list_reconciliations(batch_id) if batch_id else []
    return request.app.state.templates.TemplateResponse(request, "m6_runs.html", {"title": "批次导出", "data": data})


@router.get("/api/runs")
def runs(request: Request):
    execute({"store": request.app.state.store})
    return {"runs": request.app.state.store.all()}


@router.get("/api/export/differences.csv")
def export(request: Request):
    service = request.app.state.batches
    batch_id = request.query_params.get("batch_id")
    snapshot_id = request.query_params.get("snapshot_id")
    if batch_id:
        rows = _batch_rows(service, batch_id, snapshot_id)
        snapshot = service.resolve_snapshot(batch_id, snapshot_id)
        return Response(
            csv_text(rows), media_type="text/csv",
            headers={"Content-Disposition":
                     f"attachment; filename=evidence-{snapshot['snapshot_id']}.csv"},
        )
    data = execute({"store": request.app.state.store})
    return Response(data["csv"], media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=evidence.csv"})
