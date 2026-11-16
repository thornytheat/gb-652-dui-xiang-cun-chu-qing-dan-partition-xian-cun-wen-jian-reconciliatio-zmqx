from fastapi import APIRouter, Body, Request
from .service import execute
router = APIRouter(tags=["M1-清单采信"])

@router.get("/manifest")
def page(request: Request):
    data = execute()
    return request.app.state.templates.TemplateResponse(request, "m1_manifest.html", {"title": "清单采信", "data": data})

@router.post("/api/manifests/import")
def api(payload: dict = Body(default={})):
    return execute(payload or None)
