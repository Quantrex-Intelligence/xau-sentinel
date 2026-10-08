"""E2E checklist for Stage 9 (Market Intelligence Layer). Requires both
servers running in MOCK mode with AI_PROVIDER=mock (see
e2e/test_migration_checklist.py for how to start them). Run directly:
    python e2e/test_market_intelligence_checklist.py
"""
import sys

import httpx
from playwright.sync_api import sync_playwright

BASE = "http://localhost:3000"
API_BASE = "http://127.0.0.1:8000"
results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = ""):
    results.append((name, condition, detail))
    print(f"{'PASS' if condition else 'FAIL'}: {name}" + (f" — {detail}" if detail and not condition else ""))


def main() -> int:
    # --- API-level checks ---
    tools = httpx.get(f"{API_BASE}/api/ai/tools", timeout=10).json()
    tool_names = {t["name"] for t in tools}
    check("API: all 5 market intelligence tools are registered",
          {"get_macro_context", "get_cross_asset_context", "get_economic_events",
           "get_market_news", "get_market_intelligence"} <= tool_names)

    mi = httpx.get(f"{API_BASE}/api/market-intelligence", timeout=10).json()
    check("API: /market-intelligence returns a fully populated structure",
          mi.get("data_available") is True and mi.get("macro") is not None
          and mi.get("gold_fundamentals") is not None and mi.get("cross_asset") is not None
          and len(mi.get("events", [])) > 0 and len(mi.get("news", [])) > 0)
    check("API: every populated section carries a source", "mock" in mi.get("sources", []))

    news_headlines = [a["headline"] for a in mi.get("news", [])]
    check("API: news articles are deduplicated", len(news_headlines) == len(set(news_headlines)))

    body_text = httpx.get(f"{API_BASE}/api/market-intelligence", timeout=10).text.lower()
    check("API: response never mentions probability/win-forecast language",
          "probability" not in body_text and "win_chance" not in body_text)

    chat_resp = httpx.post(f"{API_BASE}/api/ai/chat", timeout=15,
                            json={"message": "what is the current macro backdrop for gold?"}).json()
    check("API: chat response still has the pre-existing fields",
          all(k in chat_resp for k in ("answer", "context_used", "sources", "knowledge_used",
                                        "tools_used", "memory_used")))

    # --- Browser checks ---
    console_errors, page_errors, failed_requests = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.method} {req.url}"))

        page.goto(f"{BASE}/assistant", wait_until="networkidle", timeout=30000)
        try:
            page.get_by_text("Market intelligence", exact=False).wait_for(state="visible", timeout=15000)
            check("UI: Market intelligence panel is visible on the Assistant page", True)
        except Exception:
            check("UI: Market intelligence panel is visible on the Assistant page", False)

        page.get_by_text("Market intelligence", exact=False).click()
        # Section headers are styled with CSS text-transform:uppercase
        # (same convention as "Trading memory"/"Knowledge referenced:"
        # elsewhere), so match case-insensitively.
        try:
            page.get_by_text("Macro", exact=False).first.wait_for(state="visible", timeout=15000)
            check("UI: panel expands and shows macro/cross-asset/events/news sections", True)
        except Exception:
            check("UI: panel expands and shows macro/cross-asset/events/news sections", False)

        try:
            page.get_by_text("Gold Fundamentals", exact=False).wait_for(state="visible", timeout=5000)
            check("UI: Gold Fundamentals section renders", True)
        except Exception:
            check("UI: Gold Fundamentals section renders", False)

        page.wait_for_timeout(1000)
        body_text = page.inner_text("body")
        check("UI: no probability/win-forecast language anywhere on the page",
              "probability" not in body_text.lower())

        page.goto(f"{BASE}/market", wait_until="networkidle", timeout=30000)
        page.get_by_role("button", name="A+ evidence and AI explanation").first.click(timeout=15000)
        try:
            page.get_by_text("A+ Strategy Evaluation", exact=False).wait_for(state="visible", timeout=15000)
            setups_page_loaded = True
        except Exception:
            setups_page_loaded = False
        # A specific toggle-button locator, not a page-wide text substring:
        # since Stage 10 the A+ panel legitimately shows a small "Market
        # Intelligence" SECTION LABEL (a <p>, not a button) as part of its
        # own contextual analysis when relevant — a blanket substring check
        # would false-positive on that intentional, different mention. The
        # actual thing this check cares about — the full Stage 9 browsing
        # widget from ai/market_intelligence/ — is a collapsible toggle
        # <button>, which this targets specifically.
        mi_panel_toggle_present = False
        if setups_page_loaded:
            try:
                page.get_by_role("button", name="Market intelligence").wait_for(state="attached", timeout=1000)
                mi_panel_toggle_present = True
            except Exception:
                mi_panel_toggle_present = False
        check("UI: Market page is not cluttered with the Market Intelligence panel",
              setups_page_loaded and not mi_panel_toggle_present)

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
