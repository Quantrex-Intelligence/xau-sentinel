"""Periodic Trading Digest routes (Stage 18) — thin pass-throughs into
ai.digest.service; no boundary/aggregation logic lives here. /status never
returns the Telegram bot token/chat id (mirrors
api/routes/notifications.py's /telegram/status). /preview only ever calls
service.build_digest() -- no send, no store write.
"""
from dataclasses import asdict

import config
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ai.digest import service, store
from ai.digest.models import DigestSummary, DigestType
from ai.digest.schemas import DigestSendResultOut, DigestStatusOut, DigestSummaryOut

router = APIRouter(prefix="/api/digest", tags=["digest"])


class DigestRequest(BaseModel):
    digest_type: str


def _is_configured() -> bool:
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


def _parse_digest_type(value: str) -> DigestType:
    try:
        return DigestType(value.strip().upper())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown digest_type '{value!r}'. Must be WEEKLY or MONTHLY.")


def _summary_out(summary: DigestSummary) -> DigestSummaryOut:
    data = asdict(summary)
    data["digest_type"] = summary.digest_type.value
    data["period_start"] = summary.period_start.isoformat()
    data["period_end"] = summary.period_end.isoformat()
    data["overview"]["strategy_alignment_counts"] = {
        k.value: v for k, v in summary.overview.strategy_alignment_counts.items()
    }
    data["overview"]["risk_alignment_counts"] = {
        k.value: v for k, v in summary.overview.risk_alignment_counts.items()
    }
    data["behavioral_patterns"] = [
        {**asdict(p), "deviation_type": p.deviation_type.value} for p in summary.behavioral_patterns
    ]
    if summary.previous_period is not None:
        data["previous_period"]["current_strategy_alignment_counts"] = {
            k.value: v for k, v in summary.previous_period.current_strategy_alignment_counts.items()
        }
        data["previous_period"]["previous_strategy_alignment_counts"] = {
            k.value: v for k, v in summary.previous_period.previous_strategy_alignment_counts.items()
        }
    return DigestSummaryOut(**data)


@router.get("/status", response_model=DigestStatusOut)
def get_status():
    weekly_sent = store.last_sent(DigestType.WEEKLY.value)
    monthly_sent = store.last_sent(DigestType.MONTHLY.value)
    return DigestStatusOut(
        enabled=config.DIGEST_ENABLED, weekly_enabled=config.DIGEST_WEEKLY_ENABLED,
        monthly_enabled=config.DIGEST_MONTHLY_ENABLED, weekly_day=config.DIGEST_WEEKLY_DAY,
        weekly_time=config.DIGEST_WEEKLY_TIME, monthly_day=config.DIGEST_MONTHLY_DAY,
        monthly_time=config.DIGEST_MONTHLY_TIME, provider=config.NOTIFICATION_PROVIDER,
        configured=_is_configured(),
        last_sent_weekly=weekly_sent["sent_at"] if weekly_sent else None,
        last_sent_monthly=monthly_sent["sent_at"] if monthly_sent else None,
    )


@router.post("/preview", response_model=DigestSummaryOut)
def preview_digest(body: DigestRequest):
    digest_type = _parse_digest_type(body.digest_type)
    summary = service.build_digest(digest_type)
    return _summary_out(summary)


@router.post("/send", response_model=DigestSendResultOut)
def send_digest(body: DigestRequest):
    digest_type = _parse_digest_type(body.digest_type)
    summary, sent, already_sent, error = service.attempt_send(digest_type)
    return DigestSendResultOut(sent=sent, already_sent=already_sent, error=error, summary=_summary_out(summary))
