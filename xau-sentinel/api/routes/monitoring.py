"""Monitoring alert routes (Stage 13) — read-only listing plus
acknowledgement only. Every handler is a thin call into ai.monitoring.store;
no engine/rule logic lives here. Deliberately mounted at /api/monitoring,
not /api/alerts — api/routes/alerts.py already owns that path for the
unrelated, frozen-schema Stage 1 event/alert log (see ai/monitoring/__init__.py
and the Stage 13 plan for why these are two separate systems).

Acknowledge endpoints only ever set monitoring_alerts.acknowledged — see
ai/monitoring/store.py::acknowledge()/acknowledge_all(), which have no
column and no code path capable of touching trades, strategy state, market
data, risk calculations, or A+ ratings.
"""
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ai.monitoring import store
from ai.monitoring.schemas import AcknowledgeResultOut, AlertEventOut

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


def _out(alert) -> AlertEventOut:
    data = asdict(alert)
    data["type"] = alert.type.value
    data["severity"] = alert.severity.value
    return AlertEventOut(**data)


@router.get("/alerts", response_model=list[AlertEventOut])
def get_alerts(
    type: Optional[str] = Query(None), severity: Optional[str] = Query(None),
    acknowledged: Optional[bool] = Query(None), limit: int = Query(50, ge=1, le=200),
):
    alerts = store.list_alerts(alert_type=type, severity=severity, acknowledged=acknowledged, limit=limit)
    return [_out(a) for a in alerts]


@router.get("/alerts/unread", response_model=list[AlertEventOut])
def get_unread_alerts(limit: int = Query(50, ge=1, le=200)):
    alerts = store.list_alerts(acknowledged=False, limit=limit)
    return [_out(a) for a in alerts]


@router.post("/alerts/{alert_id}/acknowledge", response_model=AcknowledgeResultOut)
def acknowledge_alert(alert_id: int):
    ok = store.acknowledge(alert_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Alert not found.")
    return AcknowledgeResultOut(acknowledged=True)


@router.post("/alerts/acknowledge-all", response_model=AcknowledgeResultOut)
def acknowledge_all_alerts():
    count = store.acknowledge_all()
    return AcknowledgeResultOut(acknowledged=True, count=count)
