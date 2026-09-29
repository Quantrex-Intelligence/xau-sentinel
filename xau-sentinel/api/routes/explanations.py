"""Explanation routes (Stage 15) — thin pass-throughs into
ai.explanations.service; no evidence-gathering/LLM logic lives here.
Never blocks alert creation (nothing in ai/monitoring/ or
ai/notifications/ calls into this module) — generation only ever happens
on an explicit request here.
"""
from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from ai.explanations import service
from ai.explanations.schemas import AlertExplanationOut

router = APIRouter(prefix="/api/explanations", tags=["explanations"])


def _out(explanation) -> AlertExplanationOut:
    return AlertExplanationOut(**asdict(explanation))


@router.get("/alert/{alert_id}", response_model=AlertExplanationOut)
def get_alert_explanation(alert_id: int):
    try:
        explanation = service.explain_alert(alert_id)
    except service.ExplanationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _out(explanation)


@router.post("/alert/{alert_id}/generate", response_model=AlertExplanationOut)
def regenerate_alert_explanation(alert_id: int):
    try:
        explanation = service.explain_alert(alert_id, force=True)
    except service.ExplanationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _out(explanation)


@router.get("/trade/{trade_id}", response_model=AlertExplanationOut)
def get_trade_explanation(trade_id: int):
    try:
        explanation = service.explain_trade(trade_id)
    except service.ExplanationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _out(explanation)


@router.post("/trade/{trade_id}/generate", response_model=AlertExplanationOut)
def regenerate_trade_explanation(trade_id: int):
    try:
        explanation = service.explain_trade(trade_id, force=True)
    except service.ExplanationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _out(explanation)
