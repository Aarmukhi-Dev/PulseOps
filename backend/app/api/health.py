from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.database import database_status

router = APIRouter()


@router.get("/health")
def health() -> JSONResponse:
    database = database_status()
    if database != "ok":
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": database},
        )
    return JSONResponse(status_code=200, content={"status": "ok", "database": "ok"})
