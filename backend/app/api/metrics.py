from fastapi import APIRouter, HTTPException, status
from fastapi import Depends

from app.core.auth import get_current_user
from app.core.metrics import MetricsUnavailableError, collect_current_metrics
from app.schemas.metrics import CurrentMetricsResponse

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])


@router.get("/current", response_model=CurrentMetricsResponse)
def get_current_metrics(_user=Depends(get_current_user)) -> CurrentMetricsResponse:
    try:
        return collect_current_metrics()
    except MetricsUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="System metrics are temporarily unavailable",
        ) from exc
