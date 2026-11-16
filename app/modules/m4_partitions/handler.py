from fastapi import APIRouter, Body, Request
from .service import execute
router = APIRouter(tags=["M4-分区判定"])

@router.get("/partitions")
def page(request: Request):
    data = execute()
    return request.app.state.templates.TemplateResponse(request, "m4_partitions.html", {"title": "分区判定", "data": data})

@router.post("/api/partitions")
def api(payload: dict = Body(default={})):
    return execute(payload or None)
