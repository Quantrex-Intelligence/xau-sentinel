"""E2E checklist for Stage 3 (AI Assistant). Requires both servers running
in MOCK mode with AI_PROVIDER=mock (no API key needed, no network calls):
    MODE=mock AI_PROVIDER=mock uvicorn api.main:app --host 127.0.0.1 --port 8000
    (cd frontend && npm run dev)   # http://localhost:3000

Run directly (not via pytest — it drives two live dev servers rather than
exercising code in-process):
    python e2e/test_ai_assistant_checklist.py
"""
import sys

import httpx
from playwright.sync_api import Page, sync_playwright

BASE = "http://localhost:3000"
API_BASE = "http://127.0.0.1:8000"
results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = ""):
    results.append((name, condition, detail))
    print(f"{'PASS' if condition else 'FAIL'}: {name}" + (f" — {detail}" if detail and not condition else ""))


def wait_for(page: Page, text: str, timeout: int = 15000) -> bool:
    try:
        page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


def main() -> int:
    # --- API-level checks first ---
    config = httpx.get(f"{API_BASE}/api/ai/config", timeout=10).json()
    check("API: /config reports configured for the mock provider",
          config["configured"] is True and config["provider"] == "mock")

    chat = httpx.post(f"{API_BASE}/api/ai/chat", json={"message": "What is the current market structure?"},
                       timeout=10).json()
    check("API: /chat returns an answer with context_used", bool(chat.get("answer")) and len(chat["context_used"]) > 0)
    check("API: default scope excludes Journal", "Journal" not in chat["context_used"])
    check("API: category is one of the four known values",
          chat["category"] in ("FACT", "CALCULATION", "INTERPRETATION", "UNKNOWN"))

    conv_id = chat["conversation_id"]
    second = httpx.post(f"{API_BASE}/api/ai/chat",
                         json={"message": "And the setup?", "conversation_id": conv_id}, timeout=10).json()
    check("API: conversation_id is stable across turns", second["conversation_id"] == conv_id)

    trade = httpx.post(f"{API_BASE}/api/journal/trades", json={
        "trade_date": "2026-01-05", "trade_time": "09:00:00", "direction": "BUY",
        "entry": 100.0, "stop_loss": 95.0, "take_profit": 110.0, "planned_rr": 2.0, "setup": "Sweep+MSS",
    }, timeout=10).json()
    trade_id = trade["id"]

    explain = httpx.post(f"{API_BASE}/api/ai/chat", json={
        "message": "Explain this trade.", "trade_id": trade_id,
    }, timeout=10).json()
    check("API: trade_id scopes context to only the captured trade",
          explain["context_used"] == ["Trade Context (captured at entry)"])

    empty = httpx.post(f"{API_BASE}/api/ai/chat", json={"message": "   "}, timeout=10)
    check("API: empty message is rejected with 400", empty.status_code == 400)

    # --- Browser checks ---
    console_errors, page_errors, failed_requests = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.method} {req.url}"))

        page.goto(f"{BASE}/assistant", wait_until="networkidle", timeout=30000)
        check("UI: Assistant page loads", wait_for(page, "AI Assistant"))
        check("UI: not shown as unconfigured in mock mode", "Not configured" not in page.inner_text("body"))
        check("UI: suggested questions are visible",
              wait_for(page, "What is the current market structure?"))

        page.get_by_text("What is the current market structure?", exact=True).click()
        check("UI: sending a suggested question shows an answer",
              wait_for(page, "Context used", timeout=20000))

        body_after_answer = page.inner_text("body")
        check("UI: answer references Market Structure in the context indicator",
              "Market Structure" in body_after_answer)

        page.get_by_text("Clear conversation", exact=True).click()
        page.wait_for_timeout(500)
        check("UI: clearing removes prior turns", "Context used" not in page.inner_text("body"))

        # Deep link from a trade: /assistant?trade=<id> auto-asks, scoped to that trade only.
        page.goto(f"{BASE}/assistant?trade={trade_id}", wait_until="networkidle", timeout=30000)
        check("UI: trade deep-link auto-asks and answers",
              wait_for(page, "Trade Context (captured at entry)", timeout=20000))

        check("UI: no browser console errors", len(console_errors) == 0 and len(page_errors) == 0,
              str(console_errors + page_errors))
        check("UI: no failed network requests", len(failed_requests) == 0, str(failed_requests))

        browser.close()

    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
