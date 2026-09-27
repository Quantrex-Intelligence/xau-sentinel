"""MT5 connection management.

This module is READ-ONLY: it only ever calls MetaTrader5's initialize/login/
shutdown/info functions. It never places, closes, or modifies an order.

The MetaTrader5 python package only runs on Windows next to a real MT5
terminal, so on any other platform (or in MODE=mock) it is simply absent and
every function below degrades to a clear "disconnected" state instead of
crashing the app.
"""
import logging

import config

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

_connected = False
_symbol_ready = False
_last_error = None


def mt5_available() -> bool:
    return mt5 is not None


def connect() -> bool:
    """Attempts to initialize and (optionally) log in to the MT5 terminal.
    Never raises — any failure is recorded via last_error() instead."""
    global _connected, _symbol_ready, _last_error

    if not config.IS_LIVE:
        _connected = False
        return False

    if mt5 is None:
        _last_error = "MetaTrader5 package is not available on this platform (Windows-only)."
        _connected = False
        return False

    try:
        if not mt5.initialize():
            _last_error = f"MT5 initialize() failed: {mt5.last_error()}"
            _connected = False
            return False

        if config.MT5_LOGIN and config.MT5_PASSWORD and config.MT5_SERVER:
            authorized = mt5.login(
                login=int(config.MT5_LOGIN),
                password=config.MT5_PASSWORD,
                server=config.MT5_SERVER,
            )
            if not authorized:
                _last_error = f"MT5 login failed: {mt5.last_error()}"
                _connected = False
                return False

        _connected = True
        _symbol_ready = _ensure_symbol()
        if not _symbol_ready:
            _last_error = f"Symbol '{config.TRADING_SYMBOL}' not found or unavailable from this broker."
        else:
            _last_error = None
        return True
    except Exception as exc:  # noqa: BLE001 - any MT5/network hiccup must not crash the app
        logger.exception("MT5 connection error")
        _last_error = str(exc)
        _connected = False
        return False


def _ensure_symbol() -> bool:
    if mt5 is None:
        return False
    info = mt5.symbol_info(config.TRADING_SYMBOL)
    if info is None:
        return False
    if not info.visible:
        return bool(mt5.symbol_select(config.TRADING_SYMBOL, True))
    return True


def disconnect() -> None:
    global _connected
    if mt5 is not None:
        try:
            mt5.shutdown()
        except Exception:  # noqa: BLE001
            pass
    _connected = False


def is_connected() -> bool:
    """Re-checks the terminal's liveness rather than trusting a cached flag."""
    global _connected
    if not config.IS_LIVE or mt5 is None:
        _connected = False
        return False
    try:
        info = mt5.terminal_info()
        _connected = info is not None and bool(info.connected)
    except Exception:  # noqa: BLE001
        _connected = False
    return _connected


def symbol_ready() -> bool:
    return _symbol_ready


def last_error():
    return _last_error


def status_label() -> tuple[str, bool]:
    """Returns (label, is_connected) for display in the header."""
    if is_connected():
        return "🟢 MT5 CONNECTED", True
    return "🔴 MT5 DISCONNECTED", False
