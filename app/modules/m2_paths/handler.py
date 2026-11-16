from fastapi import APIRouter, Body, Request
from .service import execute
router = APIRouter(tags=["M2-路径契约"])

@router.get("/paths")
def page(request: Request):
    data = execute()
    return request.app.state.templates.TemplateResponse(request, "m2_paths.html", {"title": "路径契约", "data": data})

@router.post("/api/paths/normalize")
def api(payload: dict = Body(default={})):
    return execute(payload or None)
