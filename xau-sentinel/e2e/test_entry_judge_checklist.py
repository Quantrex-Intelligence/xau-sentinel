"""E2E checklist for the Entry Model V2 LLM Setup Judge (shadow mode), read-only.

Requires both servers running in MOCK mode with AI_PROVIDER=mock:
    MODE=mock AI_PROVIDER=mock uvicorn api.main:app --host 127.0.0.1 --port 8000
    (cd frontend && npm run dev)   # http://localhost:3000

Run directly:
    python e2e/test_entry_judge_checklist.py

Read-only by design: only GET requests and page checks. Never places an order, never writes to the
journal/alerts outside its own entry_model_judgments table, never calls a real paid provider (MOCK
mode's mock provider has no API key and makes no network call).
"""
import re
import sys
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = "http://localhost:3000"
API_BASE = "http://127.0.0.1:8000"
FORBIDDEN = re.compile(r"(?<!not a )probab|\bBUY\b(?!-side)|\bSELL\b(?!-side)|win rate|guaranteed", re.IGNORECASE)
results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = ""):
    results.append((name, condition, detail))


def main() -> int:
    # --- API contract ---------------------------------------------------
    resp = httpx.get(f"{API_BASE}/api/entry-model/judge", timeout=30)
    check("API: GET /api/entry-model/judge returns 200", resp.status_code == 200, str(resp.status_code))
    body = resp.json() if resp.status_code == 200 else {}
    check("API: response always reports an enabled flag", "enabled" in body)
    check("API: response always reports an eligible flag", "eligible" in body)
    check("API: disclaimer explicitly states SHADOW MODE", "SHADOW MODE" in body.get("disclaimer", ""))
    direction, state = body.get("direction"), body.get("state")
    check("API: a verdict only appears when eligible is true",
          body.get("verdict") is None or body.get("eligible") is True)
    check("API: the route is read-only (POST is not allowed)",
          httpx.post(f"{API_BASE}/api/entry-model/judge", timeout=15).status_code in (404, 405))

    before = httpx.get(f"{API_BASE}/api/entry-model", timeout=30).json()
    httpx.get(f"{API_BASE}/api/entry-model/judge", timeout=30)
    after = httpx.get(f"{API_BASE}/api/entry-model", timeout=30).json()
    check("API: calling the judge never changes /api/entry-model's own direction/state",
          before.get("direction") == after.get("direction") and before.get("state") == after.get("state"))

    # --- Browser checks -------------------------------------------------
    console_errors, page_errors, failed_requests = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.method} {req.url}"))

        page.goto(f"{BASE}/market", wait_until="networkidle", timeout=30000)

        try:
            page.get_by_role("heading", name="LLM setup judge").wait_for(state="visible", timeout=15000)
            check("UI: the LLM Setup Judge card is shown on the Market page", True)
        except Exception:
            check("UI: the LLM Setup Judge card is shown on the Market page", False)

        card_text = page.get_by_test_id("entry-judge-card").inner_text()
        check("UI: SHADOW MODE is shown on the card", "SHADOW MODE" in card_text)
        check("UI: never claims the setup is approved or guaranteed", not FORBIDDEN.search(card_text))

        if body.get("eligible") and body.get("status") == "OK":
            check("UI: an eligible, successful evaluation shows a verdict label",
                  any(v in card_text for v in ("SUPPORTED", "CAUTION", "REJECTED", "INSUFFICIENT_EVIDENCE")))
        elif not body.get("eligible"):
            check("UI: a not-yet-eligible candidate shows a plain reason, not a blank card",
                  len(card_text.strip()) > len("LLM setup judgeSHADOW MODE"))
        else:
            check("UI: a failed evaluation says so plainly and names the deterministic engine as unaffected",
                  "fail" in card_text.lower() and "unaffected" in card_text.lower())

        check("UI: no browser console errors", len(console_errors) == 0 and len(page_errors) == 0,
              str(console_errors + page_errors))
        check("UI: no failed network requests", len(failed_requests) == 0, str(failed_requests))
        browser.close()

    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    for name, ok, detail in results:
        if not ok:
            print(f"FAIL: {name} {detail}")
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
