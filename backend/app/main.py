from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.history import router as history_router
from app.api.auth import router as auth_router
from app.api.metrics import router as metrics_router
from app.api.services import router as services_router
from app.core.config import settings
from app.core.rate_limit import LocalRateLimitMiddleware

app = FastAPI(
    title="PulseOps API",
    version="0.1.0",
    docs_url=None if settings.app_env == "production" else "/docs",
    redoc_url=None if settings.app_env == "production" else "/redoc",
    openapi_url=None if settings.app_env == "production" else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.add_middleware(LocalRateLimitMiddleware)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(services_router)
app.include_router(metrics_router)
app.include_router(history_router)
