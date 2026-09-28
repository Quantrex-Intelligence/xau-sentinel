"""E2E checklist for Stage 6 (AI Tool Calling). Requires both servers
running in MOCK mode with AI_PROVIDER=mock (see
e2e/test_migration_checklist.py for how to start them). Run directly:
    python e2e/test_tool_calling_checklist.py
"""
import re
import sys

import httpx
from playwright.sync_api import sync_playwright

BASE = "http://localhost:3000"
API_BASE = "http://127.0.0.1:8000"
results: list[tuple[str, bool, str]] = []

_WRITE_LIKE = re.compile(r"\b(place|close|modify|cancel|order|delete)\b", re.IGNORECASE)


def check(name: str, condition: bool, detail: str = ""):
    results.append((name, condition, detail))
    print(f"{'PASS' if condition else 'FAIL'}: {name}" + (f" — {detail}" if detail and not condition else ""))


def main() -> int:
    # --- API-level checks ---
    tools = httpx.get(f"{API_BASE}/api/ai/tools", timeout=10).json()
    check("API: at least 11 tools are registered", len(tools) >= 11, str(len(tools)))
    tool_names = {t["name"] for t in tools}
    check("API: market/risk/journal/knowledge tools are all present",
          {"get_market_state", "get_risk_status", "get_open_positions", "search_journal",
           "search_strategy"} <= tool_names)
    check("API: no registered tool name looks write-capable",
          not any(_WRITE_LIKE.search(n) for n in tool_names), str(tool_names))

    tool_call_resp = httpx.post(f"{API_BASE}/api/ai/chat", timeout=15,
                                 json={"message": "Why is this setup only developing?"}).json()
    check("API: a matching question triggers a tool call", len(tool_call_resp.get("tools_used", [])) > 0)
    if tool_call_resp.get("tools_used"):
        check("API: the tool call reports the current setup tool",
              tool_call_resp["tools_used"][0]["name"] == "get_current_setup",
              str(tool_call_resp["tools_used"]))
    check("API: tool-calling response still has the pre-existing fields",
          all(k in tool_call_resp for k in ("answer", "context_used", "sources", "knowledge_used")))

    no_tool_resp = httpx.post(f"{API_BASE}/api/ai/chat", timeout=15, json={"message": "hello there"}).json()
    check("API: an unmatched message calls no tool", no_tool_resp.get("tools_used") == [])

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
            page.get_by_placeholder("Ask about market structure").wait_for(state="visible", timeout=15000)
            check("UI: Assistant page loads", True)
        except Exception:
            check("UI: Assistant page loads", False)

        # The "Tools used:" label is styled with CSS text-transform:uppercase
        # (same convention as "Knowledge referenced:"), so Playwright's
        # rendered inner_text reports it as "TOOLS USED:".
        page.fill("input[placeholder*='Ask about market structure']", "Why is this setup only developing?")
        page.get_by_role("button", name="Send").click()
        try:
            page.get_by_text("TOOLS USED:", exact=False).wait_for(state="visible", timeout=15000)
            check("UI: tools used panel shown for a matching question", True)
        except Exception:
            check("UI: tools used panel shown for a matching question", False)

        page.fill("input[placeholder*='Ask about market structure']", "hello there")
        page.get_by_role("button", name="Send").click()
        page.wait_for_timeout(2000)
        body_text = page.inner_text("body")
        # Only one "TOOLS USED:" panel should be present (from the first,
        # matching turn) — the second turn (no keyword match) adds none.
        check("UI: an unmatched follow-up question does not add a second tools panel",
              body_text.count("TOOLS USED:") == 1)

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
