"""E2E checklist for Stage 7 (Trading Memory). Requires both servers
running in MOCK mode with AI_PROVIDER=mock (see
e2e/test_migration_checklist.py for how to start them). Run directly:
    python e2e/test_trading_memory_checklist.py
"""
import sys
import time

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
    created = httpx.post(f"{API_BASE}/api/ai/memory", timeout=10, json={
        "category": "TRADE_LESSON",
        "content": "E2E: user repeatedly enters too early before the retracement completes.",
    }).json()
    memory_id = created["id"]
    check("API: created memory has source=user_confirmed", created.get("source") == "user_confirmed")
    check("API: created memory is ACTIVE", created.get("status") == "ACTIVE")

    listed = httpx.get(f"{API_BASE}/api/ai/memory", timeout=10).json()
    check("API: new memory appears in the default listing", any(m["id"] == memory_id for m in listed))

    tools = httpx.get(f"{API_BASE}/api/ai/tools", timeout=10).json()
    tool_names = {t["name"] for t in tools}
    check("API: search_memory and get_memory tools are registered",
          {"search_memory", "get_memory"} <= tool_names)

    relevant = httpx.post(f"{API_BASE}/api/ai/chat", timeout=15,
                           json={"message": "why do I enter too early?"}).json()
    check("API: relevant question returns memory_used", len(relevant.get("memory_used", [])) > 0)
    check("API: chat response still has the pre-existing fields",
          all(k in relevant for k in ("answer", "context_used", "sources", "knowledge_used", "tools_used")))

    no_source_leak = httpx.post(f"{API_BASE}/api/ai/memory", timeout=10, json={
        "category": "USER_PREFERENCE", "content": "E2E: trying to fake a source.", "source": "assistant_auto",
    }).json()
    check("API: a client-supplied source field is ignored",
          no_source_leak.get("source") == "user_confirmed")

    archived = httpx.post(f"{API_BASE}/api/ai/memory/{memory_id}/archive", timeout=10).json()
    check("API: archive sets status to ARCHIVED", archived.get("status") == "ARCHIVED")

    after_archive = httpx.post(f"{API_BASE}/api/ai/chat", timeout=15,
                                json={"message": "why do I enter too early?"}).json()
    check("API: an archived memory no longer surfaces in retrieval",
          not any(m["id"] == memory_id for m in after_archive.get("memory_used", [])))

    default_listing = httpx.get(f"{API_BASE}/api/ai/memory", timeout=10).json()
    check("API: archived memory excluded from the default listing",
          not any(m["id"] == memory_id for m in default_listing))

    # Cleanup: archive the second, source-leak test record too.
    httpx.post(f"{API_BASE}/api/ai/memory/{no_source_leak['id']}/archive", timeout=10)

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

        try:
            page.get_by_text("Trading memory", exact=False).wait_for(state="visible", timeout=10000)
            check("UI: Trading memory panel is visible", True)
        except Exception:
            check("UI: Trading memory panel is visible", False)

        page.get_by_text("Trading memory", exact=False).click()
        page.wait_for_timeout(1000)

        # The panel content ("Describe the preference...") only renders once expanded.
        try:
            page.get_by_placeholder("Describe the preference", exact=False).wait_for(state="visible", timeout=5000)
            check("UI: memory panel expands to show the add-memory form", True)
        except Exception:
            check("UI: memory panel expands to show the add-memory form", False)

        # Unique per run (not a fixed literal) so repeated runs never leave
        # behind multiple identical records that later make get_by_text
        # ambiguous (Playwright's strict mode throws on >1 match) — the
        # exact "test-data accumulation" trap documented in project memory.
        ui_memory_text = f"E2E UI: user prefers trading only the London session ({time.time():.0f})."
        page.fill("textarea[placeholder*='Describe the preference']", ui_memory_text)
        page.get_by_role("button", name="Save to memory").click()
        try:
            page.get_by_text(ui_memory_text, exact=False).wait_for(state="visible", timeout=10000)
            check("UI: a saved memory appears in the panel list", True)
        except Exception:
            check("UI: a saved memory appears in the panel list", False)

        # "Save to memory" also appears under each assistant turn (a
        # different, per-turn draft action — distinct from the panel's own
        # button of the same label used just above). Ask about the memory
        # just saved above (the earlier API-created one is already
        # archived by this point in the script) so retrieval has something
        # active and relevant to surface.
        page.fill("input[placeholder*='Ask about market structure']", "what session do I prefer trading?")
        page.get_by_role("button", name="Send").click()
        page.wait_for_timeout(2000)
        # The label is styled with CSS text-transform:uppercase, same
        # convention as "Knowledge referenced:"/"Tools used:".
        try:
            page.get_by_text("MEMORY REFERENCED:", exact=False).wait_for(state="visible", timeout=15000)
            check("UI: memory referenced panel shown for a matching question", True)
        except Exception:
            check("UI: memory referenced panel shown for a matching question", False)

        check("UI: no browser console errors", len(console_errors) == 0 and len(page_errors) == 0,
              str(console_errors + page_errors))
        check("UI: no failed network requests", len(failed_requests) == 0, str(failed_requests))

        browser.close()

    # Cleanup: archive the UI-created record too, so repeated runs never
    # accumulate live rows (the unique suffix above already prevents THIS
    # run's row from colliding with a past one, but leaving it ACTIVE would
    # still grow the memory panel's list indefinitely across runs).
    ui_created = [m for m in httpx.get(f"{API_BASE}/api/ai/memory", timeout=10).json()
                  if m["content"] == ui_memory_text]
    for m in ui_created:
        httpx.post(f"{API_BASE}/api/ai/memory/{m['id']}/archive", timeout=10)

    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
