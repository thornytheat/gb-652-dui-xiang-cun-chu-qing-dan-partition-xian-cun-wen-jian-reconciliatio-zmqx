import json
from pathlib import Path

from fastapi import APIRouter, Body, Request
from .service import execute

router = APIRouter(tags=["M3-对象核验"])
SAMPLE_STREAM = Path(__file__).resolve().parents[3] / "sample_data" / "objects.jsonl"


def _sample_objects() -> list[dict]:
    if not SAMPLE_STREAM.exists():
        return []
    text = SAMPLE_STREAM.read_text(encoding="utf-8")
    # 随仓样例把换行存成了字面 "\n"（文件本身只有一行）；只在没有真实换行时反转义。
    if "\n" not in text and "\\n" in text:
        text = text.replace("\\n", "\n").replace("\\r", "\r")
    out = []
    for line in text.splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


@router.get("/objects")
def page(request: Request):
    service = request.app.state.batches
    batch_id = request.query_params.get("batch_id")
    data = execute()
    data["batch_id"] = batch_id
    data["batch_missing"] = False
    data["batch"] = None
    data["snapshots"] = []
    data["batches"] = [service.batch_view(b) for b in service.store.list_batches()]
    if batch_id:
        if service.store.get_batch(batch_id):
            batch = service.store.get_batch(batch_id)
            data["batch"] = service.batch_view(batch)
            data["snapshots"] = service.store.batch_snapshots(batch_id)
        else:
            data["batch_missing"] = True
    data["sample_stream"] = _sample_objects()
    return request.app.state.templates.TemplateResponse(request, "m3_objects.html", {"title": "对象核验", "data": data})


@router.post("/api/objects/verify")
def api(request: Request, payload: dict = Body(default={})):
    service = request.app.state.batches
    if payload and (payload.get("batch_id") or payload.get("collection_id")):
        return service.collect(payload)
    return execute(payload or None)
