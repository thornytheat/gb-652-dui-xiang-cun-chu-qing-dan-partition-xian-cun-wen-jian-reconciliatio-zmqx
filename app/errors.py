from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

class DomainError(ValueError):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)

class CollectionInterrupted(DomainError):
    """采集中断：已经采到的对象已落盘，游标保留，但不发布半批。"""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__("COLLECTION_INTERRUPTED", message)
        self.details = details or {}

CONFLICT_CODES = {"COLLECTION_INTERRUPTED"}

def install(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        status = 409 if exc.code in CONFLICT_CODES else 422
        content = {"error": exc.code, "message": exc.message}
        if isinstance(exc, CollectionInterrupted):
            content |= exc.details
        return JSONResponse(status_code=status, content=content)
