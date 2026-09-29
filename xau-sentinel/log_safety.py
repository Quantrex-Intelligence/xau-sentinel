"""Secret-safe logging for third-party HTTP clients (VAL-036).

Telegram's Bot API puts the bot token in the request path
(https://api.telegram.org/bot<TOKEN>/sendMessage), and httpx logs every
request URL at INFO ("HTTP Request: POST https://api.telegram.org/bot...").
Nothing in this project raises httpx's logger to INFO today, so there is no
active leak — but one `logging.basicConfig(level=logging.INFO)` added later
would silently start writing the token to every log.

Two independent layers, so that future config change can't undo both:
1. httpx/httpcore are pinned to WARNING, so request-URL lines aren't
   emitted at all by default.
2. A redaction filter on those same loggers rewrites any `bot<token>` path
   segment to `bot<redacted>` in every record that still gets through —
   including one where someone deliberately lowers the level again.
"""
import logging
import re

_HTTP_LOGGERS = ("httpx", "httpcore")
_BOT_TOKEN = re.compile(r"/bot[^/\s\"']+")
REDACTED = "/bot<redacted>"


def redact_secrets(text: str) -> str:
    return _BOT_TOKEN.sub(REDACTED, text)


class RedactBotTokenFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = redact_secrets(message)
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True


def install() -> None:
    """Idempotent — safe to call from every entry point."""
    for name in _HTTP_LOGGERS:
        logger = logging.getLogger(name)
        if logger.level == logging.NOTSET or logger.level < logging.WARNING:
            logger.setLevel(logging.WARNING)
        if not any(isinstance(f, RedactBotTokenFilter) for f in logger.filters):
            logger.addFilter(RedactBotTokenFilter())
