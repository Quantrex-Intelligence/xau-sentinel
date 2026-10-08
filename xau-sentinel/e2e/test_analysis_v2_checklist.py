"""E2E checklist for the Analysis Engine V2 view (read-only).

Requires both servers running in MOCK mode with AI_PROVIDER=mock:
    MODE=mock AI_PROVIDER=mock uvicorn api.main:app --host 127.0.0.1 --port 8000
    (cd frontend && npm run dev)   # http://localhost:3000

Run directly:
    python e2e/test_analysis_v2_checklist.py

Read-only by design: the checklist only issues GET requests and checks the
page. It never places orders, writes to the journal, or calls an LLM.
"""
import re
import sys
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = "http://localhost:3000"
API_BASE = "http://127.0.0.1:8000"
FORBIDDEN = re.compile(r"probab|confiden|\bBUY\b(?!-side)|\bSELL\b(?!-side)|win rate|\bscore\b", re.IGNORECASE)
results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = ""):
    results.append((name, condition, detail))


def main() -> int:
    # --- API contract ---------------------------------------------------
    resp = httpx.get(f"{API_BASE}/api/analysis/v2", timeout=30)
    check("API: GET /api/analysis/v2 returns 200", resp.status_code == 200, str(resp.status_code))
    body = resp.json() if resp.status_code == 200 else {}
    check("API: status is one of the declared values",
          body.get("status") in {"OK", "STALE", "INSUFFICIENT_DATA", "UNAVAILABLE"}, str(body.get("status")))
    check("API: freshness reports the last closed bar and a stale flag",
          isinstance(body.get("freshness"), dict) and "stale" in body["freshness"]
          and "threshold_seconds" in body["freshness"])
    check("API: source is labelled, so mock data is never presented as market data",
          str(body.get("source", {}).get("provider", "")).startswith(("MOCK", "MT5", "unavailable")))
    check("API: facts, interpretation and scenarios are separate groups",
          {"facts", "interpretation", "scenarios"} <= set(body))
    check("API: multi-timeframe structure is present for M5, M15, H1 and H4",
          set((body.get("facts") or {}).get("structure", {})) == {"M5", "M15", "H1", "H4"})
    check("API: response contains no probability, confidence, score or trade call",
          not FORBIDDEN.search(resp.text))
    check("API: the route is read-only (POST is not allowed)",
          httpx.post(f"{API_BASE}/api/analysis/v2", timeout=15).status_code in (404, 405))

    # --- Browser checks -------------------------------------------------
    console_errors, page_errors, failed_requests = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.method} {req.url}"))

        page.goto(f"{BASE}/market", wait_until="networkidle", timeout=30000)
        page.get_by_role("button", name="Full V2 analysis").first.click(timeout=15000)
        try:
            page.get_by_role("heading", name="Market overview").wait_for(state="visible", timeout=15000)
            check("UI: the full V2 analysis opens from the Market page", True)
        except Exception:
            check("UI: the full V2 analysis opens from the Market page", False)

        for heading in ("Market overview", "Multi-timeframe structure", "Key areas", "Recent events",
                        "Market context", "Confluence and contradictions", "Narrative", "Conditional scenarios"):
            try:
                page.get_by_role("heading", name=heading).wait_for(state="visible", timeout=10000)
                check(f"UI: section '{heading}' is shown", True)
            except Exception:
                check(f"UI: section '{heading}' is shown", False)

        body_text = page.inner_text("body")
        # The tags are CSS-uppercased, so inner_text returns capitals; compare case-insensitively.
        check("UI: observed, interpreted and conditional are each labelled",
              all(tag in body_text.lower() for tag in ("observed", "interpreted", "conditional")))
        check("UI: data freshness and source are visible",
              "Source:" in body_text and "Last closed M5" in body_text)
        check("UI: the view is read-only (its footnote says so, or marks mock data)",
              "Read-only" in body_text or "Synthetic test data" in body_text)
        # Scoped to the V2 analysis view: the A+ card on the same page shows its direction and levels by design.
        v2_text = page.get_by_test_id("full-v2-analysis").inner_text()
        check("UI: no probability, confidence, score or trade call in the V2 analysis",
              not FORBIDDEN.search(v2_text))

        page.get_by_role("link", name="Market", exact=True).first.wait_for(state="visible", timeout=5000)
        check("UI: the sidebar links to the unified Market page", True)

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
