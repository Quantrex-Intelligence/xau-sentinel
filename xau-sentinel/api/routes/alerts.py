import json

from fastapi import APIRouter, Query

from journal import trades as trades_repo

from api.schemas import AlertOut, EventOut

router = APIRouter(prefix="/api", tags=["alerts"])


@router.get("/alerts", response_model=list[AlertOut])
def get_alerts(limit: int = Query(10, ge=1, le=100)):
    df = trades_repo.recent_alerts(limit)
    out = []
    for row in df.to_dict(orient="records"):
        details = row.get("details")
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except (TypeError, ValueError):
                pass
        out.append(AlertOut(id=row["id"], alert_time=row["alert_time"], level=row["level"],
                             direction=row.get("direction"), message=row["message"], details=details))
    return out


@router.get("/events", response_model=list[EventOut])
def get_events(limit: int = Query(10, ge=1, le=100)):
    df = trades_repo.recent_events(limit)
    return [EventOut(**row) for row in df.to_dict(orient="records")]
