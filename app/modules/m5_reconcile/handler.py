from fastapi import APIRouter, Body, Request
from .service import execute
router = APIRouter(tags=["M5-差异对账"])

@router.get("/reconcile")
def page(request: Request):
    data = execute()
    return request.app.state.templates.TemplateResponse(request, "m5_reconcile.html", {"title": "差异对账", "data": data})

@router.post("/api/reconcile")
def api(payload: dict = Body(default={})):
    return execute(payload or None)
