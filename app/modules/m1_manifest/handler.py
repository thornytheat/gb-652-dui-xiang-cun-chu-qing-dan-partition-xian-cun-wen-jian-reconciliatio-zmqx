from fastapi import APIRouter, Body, Request
from .service import execute
from app.batches import BatchService
from app.modules.m1_manifest import core

router = APIRouter(tags=["M1-清单采信"])

@router.get("/manifest")
def page(request: Request):
    service: BatchService = request.app.state.batches
    batches = [service.batch_view(batch) for batch in service.store.list_batches()]
    data = execute()
    data["batches"] = batches
    data["sample_text"] = core.SAMPLE["text"]
    return request.app.state.templates.TemplateResponse(request, "m1_manifest.html", {"title": "清单采信", "data": data})

@router.post("/api/manifests/import")
def api(request: Request, payload: dict = Body(default={})):
    service: BatchService = request.app.state.batches
    return service.import_manifest(payload or {})

@router.get("/api/batches")
def list_batches(request: Request):
    service: BatchService = request.app.state.batches
    return {"batches": [service.batch_view(batch) for batch in service.store.list_batches()]}

@router.get("/api/batches/{batch_id}")
def get_batch(request: Request, batch_id: str):
    service: BatchService = request.app.state.batches
    batch = service.require_batch(batch_id)
    view = service.batch_view(batch)
    view["snapshots"] = service.store.batch_snapshots(batch_id)
    view["reconciliations"] = service.store.list_reconciliations(batch_id)
    return view
