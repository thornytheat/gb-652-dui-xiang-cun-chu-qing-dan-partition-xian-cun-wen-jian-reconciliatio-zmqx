from fastapi import APIRouter, Body, Request
from .service import execute
router = APIRouter(tags=["M3-对象核验"])

@router.get("/objects")
def page(request: Request):
    data = execute()
    return request.app.state.templates.TemplateResponse(request, "m3_objects.html", {"title": "对象核验", "data": data})

@router.post("/api/objects/verify")
def api(payload: dict = Body(default={})):
    return execute(payload or None)
