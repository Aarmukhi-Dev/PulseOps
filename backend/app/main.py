from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.history import router as history_router
from app.api.metrics import router as metrics_router
from app.api.services import router as services_router
from app.core.config import settings

app = FastAPI(title="PulseOps API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(services_router)
app.include_router(metrics_router)
app.include_router(history_router)
