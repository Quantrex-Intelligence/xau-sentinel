"use client";

import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Archive } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { MemoryCategory, MemoryRecord } from "@/lib/types";

const CATEGORIES: MemoryCategory[] = [
  "USER_PREFERENCE", "STRATEGY_MEMORY", "TRADE_LESSON", "PATTERN_OBSERVATION",
];

/** Minimal inspect/archive/add surface for Stage 7's trading memory — a
 * collapsible addition to the assistant page, not a redesign. Every write
 * here (create, archive) is the one and only explicit-confirmation path:
 * nothing the assistant says ever reaches this component automatically —
 * see chat-message.tsx's separate "Save to memory" action for how a turn's
 * answer gets HERE (always via the user reviewing and confirming a form,
 * never silently). */
export function MemoryPanel({ prefill, onPrefillConsumed }: {
  prefill?: string;
  onPrefillConsumed?: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [category, setCategory] = useState<MemoryCategory>("TRADE_LESSON");
  const [content, setContent] = useState("");
  const [strategyVersion, setStrategyVersion] = useState("");
  const [saving, setSaving] = useState(false);

  function refresh() {
    setLoading(true);
    api
      .memoryList()
      .then(setMemories)
      .catch(() => setError("Could not load memory."))
      .finally(() => setLoading(false));
  }

  function toggleExpanded() {
    setExpanded((v) => {
      const next = !v;
      if (next) refresh();
      return next;
    });
  }

  // Adjusting state when a prop changes, without an Effect (React's own
  // recommended pattern) — state, not a ref, tracks the last prefill we've
  // already applied, so the comparison and update both happen directly
  // during render rather than in a useEffect body.
  const [appliedPrefill, setAppliedPrefill] = useState<string | undefined>(undefined);
  if (prefill && prefill !== appliedPrefill) {
    setAppliedPrefill(prefill);
    setExpanded(true);
    setContent(prefill);
  }

  useEffect(() => {
    if (prefill) onPrefillConsumed?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill]);

  async function handleSave() {
    if (!content.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      await api.memoryCreate({
        category, content: content.trim(),
        strategy_version: strategyVersion.trim() || undefined,
      });
      setContent("");
      setStrategyVersion("");
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save memory.");
    } finally {
      setSaving(false);
    }
  }

  async function handleArchive(id: number) {
    try {
      await api.memoryArchive(id);
      setMemories((prev) => prev.filter((m) => m.id !== id));
    } catch {
      setError("Could not archive memory.");
    }
  }

  return (
    <div className="rounded-md border border-border bg-card">
      <button
        onClick={toggleExpanded}
        className="w-full flex items-center gap-1.5 px-4 py-3 text-xs font-semibold tracking-wide text-muted-foreground uppercase"
      >
        {expanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        Trading memory
      </button>

      {expanded && (
        <div className="px-4 pb-4 flex flex-col gap-3">
          <p className="text-xs text-muted-foreground -mt-1">
            User-confirmed preferences, strategy decisions, trade lessons, and patterns. Never authoritative
            live data — the assistant can never create, edit, or archive these itself.
          </p>

          <div className="flex flex-col gap-2 border border-border rounded-md p-3">
            <div className="flex gap-2">
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value as MemoryCategory)}
                className="rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground"
              >
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
              <input
                value={strategyVersion}
                onChange={(e) => setStrategyVersion(e.target.value)}
                placeholder="Strategy version (optional)"
                className="flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground placeholder:text-muted-foreground"
              />
            </div>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="Describe the preference, decision, lesson, or pattern to remember…"
              rows={3}
              className="rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground placeholder:text-muted-foreground resize-none"
            />
            <button
              onClick={handleSave}
              disabled={saving || !content.trim()}
              className="self-end rounded-md bg-primary text-primary-foreground text-xs font-medium px-3 py-1.5 disabled:opacity-50"
            >
              Save to memory
            </button>
          </div>

          {error && <p className="text-xs text-bearish">{error}</p>}

          {loading ? (
            <p className="text-xs text-muted-foreground">Loading…</p>
          ) : memories.length === 0 ? (
            <p className="text-xs text-muted-foreground">No active memories yet.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {memories.map((m) => (
                <li key={m.id} className="flex items-start justify-between gap-2 border-t border-border pt-2 text-xs">
                  <div>
                    <span className="uppercase tracking-wide text-muted-foreground">{m.category}</span>
                    <p className="text-foreground mt-0.5">{m.content}</p>
                  </div>
                  <button
                    onClick={() => handleArchive(m.id)}
                    title="Archive this memory"
                    className="shrink-0 text-muted-foreground hover:text-foreground"
                  >
                    <Archive className="size-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
