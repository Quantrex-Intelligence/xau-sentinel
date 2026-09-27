"""AI assistant routes — a thin wrapper over ai.assistant.chat(). Provider
and configuration failures map to specific HTTP statuses (not a bare 500)
so the frontend can show a clear message instead of a generic error, per
the Stage 3 spec's "clear configuration error rather than crash" rule."""
from fastapi import APIRouter, HTTPException

import config
from ai import assistant
from ai.providers import get_provider
from ai.providers.base import ProviderConfigError, ProviderRequestError, ProviderResponseError
from ai.schemas import AiConfigOut, ChatRequestIn, ChatResponseOut

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/config", response_model=AiConfigOut)
def get_config():
    """Lets the frontend show a configuration error up front, before the
    user even sends a message. Never returns the API key itself — only
    whether one is usably configured."""
    try:
        provider = get_provider()
        return AiConfigOut(configured=True, provider=provider.name, model=provider.model)
    except ProviderConfigError as exc:
        return AiConfigOut(configured=False, provider=config.AI_PROVIDER, model=None, reason=str(exc))


@router.post("/chat", response_model=ChatResponseOut)
def chat(payload: ChatRequestIn):
    if not payload.message or not payload.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")

    try:
        return assistant.chat(payload.message, payload.conversation_id, payload.context_scope, payload.trade_id)
    except ProviderConfigError as exc:
        raise HTTPException(status_code=503, detail=f"AI assistant not configured: {exc}")
    except ProviderRequestError as exc:
        raise HTTPException(status_code=502, detail=f"AI provider request failed: {exc}")
    except ProviderResponseError as exc:
        raise HTTPException(status_code=502, detail=f"AI provider returned an invalid response: {exc}")
