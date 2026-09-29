"use client";

import { useEffect, useRef, useState } from "react";
import { Bell } from "lucide-react";
import { api } from "@/lib/api";
import { usePolling } from "@/lib/use-polling";
import { cn } from "@/lib/utils";
import type { AlertExplanation, MonitoringAlert } from "@/lib/types";

const SEVERITY_STYLE: Record<string, string> = {
  INFO: "bg-muted text-muted-foreground",
  WARNING: "bg-warning/10 text-warning",
  CRITICAL: "bg-bearish/10 text-bearish",
};

function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span className={cn("text-[9px] font-semibold uppercase px-1.5 py-0.5 rounded", SEVERITY_STYLE[severity] ?? "bg-muted text-muted-foreground")}>
      {severity}
    </span>
  );
}

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, { hour12: false });
  } catch {
    return iso;
  }
}

/** One compact, labeled subsection — omitted entirely when empty, per
 * the "avoid padding a section with nothing useful" convention this
 * project already follows for evidence rendering. */
function ExplanationSection({ label, lines }: { label: string; lines: string[] }) {
  if (lines.length === 0) return null;
  return (
    <div className="mt-1.5">
      <p className="text-[9px] font-semibold text-muted-foreground uppercase">{label}</p>
      {lines.map((line, i) => (
        <p key={i} className="text-foreground">{line}</p>
      ))}
    </div>
  );
}

/** Stage 15: the structured FACT/CONTEXT/INTERPRETATION explanation for
 * one alert, rendered inline (no new modal/page — matches "keep the
 * interface compact and readable"). */
function ExplanationPanel({ explanation }: { explanation: AlertExplanation }) {
  return (
    <div className="mt-2 border-t border-border pt-2 text-[11px]">
      <p className="text-foreground font-medium">{explanation.summary}</p>
      <ExplanationSection label="Deterministic facts" lines={explanation.deterministic_facts} />
      <ExplanationSection label="Context" lines={explanation.supporting_context} />
      {explanation.historical_context && (
        <ExplanationSection label="Historical context" lines={[explanation.historical_context]} />
      )}
      <ExplanationSection label="Strategy knowledge" lines={explanation.knowledge_context} />
      <ExplanationSection label="Risk" lines={explanation.risk_context} />
      <ExplanationSection label="Interpretation" lines={[explanation.interpretation]} />
      <ExplanationSection label="Uncertainties" lines={explanation.uncertainties} />
      {explanation.sources.length > 0 && (
        <p className="mt-1.5 text-[9px] text-muted-foreground">Sources: {explanation.sources.join(", ")}</p>
      )}
    </div>
  );
}

function AlertRow({ alert, onAcknowledge }: { alert: MonitoringAlert; onAcknowledge: (id: number) => void }) {
  const isAPlus = alert.type === "APLUS_SETUP_DETECTED";
  const [showExplanation, setShowExplanation] = useState(false);
  const [explanation, setExplanation] = useState<AlertExplanation | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  async function handleToggleExplain() {
    const next = !showExplanation;
    setShowExplanation(next);
    if (next && explanation === null && !loading) {
      setLoading(true);
      setError(false);
      try {
        const result = await api.explainAlert(alert.id);
        setExplanation(result);
      } catch {
        setError(true);
      } finally {
        setLoading(false);
      }
    }
  }

  return (
    <div
      className={cn(
        "py-2 border-b border-border last:border-0 text-xs",
        isAPlus && "border-l-2 border-l-bullish pl-2 -ml-2"
      )}
    >
      <div className="flex items-center gap-2">
        {isAPlus && <span className="text-[9px] font-bold text-bullish bg-bullish/10 px-1 py-0.5 rounded">A+</span>}
        <SeverityBadge severity={alert.severity} />
        <span className="text-[10px] text-muted-foreground ml-auto">{formatTimestamp(alert.timestamp)}</span>
      </div>
      <p className="text-foreground mt-1">{alert.message}</p>
      <div className="flex items-center gap-3 mt-1">
        {!alert.acknowledged && (
          <button
            onClick={() => onAcknowledge(alert.id)}
            className="text-[10px] text-muted-foreground hover:text-foreground underline"
          >
            Acknowledge
          </button>
        )}
        <button
          onClick={handleToggleExplain}
          className="text-[10px] text-muted-foreground hover:text-foreground underline"
        >
          {showExplanation ? "Hide explanation" : "Explain"}
        </button>
      </div>

      {showExplanation && (
        loading ? (
          <p className="text-[10px] text-muted-foreground mt-2">Loading explanation…</p>
        ) : error ? (
          <p className="text-[10px] text-muted-foreground mt-2">Explanation unavailable.</p>
        ) : explanation ? (
          <ExplanationPanel explanation={explanation} />
        ) : null
      )}
    </div>
  );
}

/** Stage 13: a small notification bell in the top bar — polls
 * GET /api/monitoring/alerts/unread (the docstring on lib/use-polling.ts
 * already earmarks this hook for "alerts"), never a second WebSocket
 * channel. Locally acknowledged ids are hidden immediately for snappy
 * feedback; the next poll (15s) confirms it server-side either way. */
export function NotificationBell() {
  const { data: unread } = usePolling(() => api.unreadAlerts(), 15000);
  const [expanded, setExpanded] = useState(false);
  const [locallyAcked, setLocallyAcked] = useState<Set<number>>(new Set());
  const [showAll, setShowAll] = useState(false);
  const [allAlerts, setAllAlerts] = useState<MonitoringAlert[] | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setExpanded(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const visibleUnread = (unread ?? []).filter((a) => !locallyAcked.has(a.id));
  const unreadCount = visibleUnread.length;

  async function handleAcknowledge(id: number) {
    setLocallyAcked((prev) => new Set(prev).add(id));
    setAllAlerts((prev) => prev && prev.map((a) => (a.id === id ? { ...a, acknowledged: true } : a)));
    try {
      await api.acknowledgeAlert(id);
    } catch {
      // next poll will reconcile either way
    }
  }

  async function handleAcknowledgeAll() {
    const ids = new Set(visibleUnread.map((a) => a.id));
    setLocallyAcked(ids);
    setAllAlerts((prev) => prev && prev.map((a) => (ids.has(a.id) ? { ...a, acknowledged: true } : a)));
    try {
      await api.acknowledgeAllAlerts();
    } catch {
      // next poll will reconcile either way
    }
  }

  async function handleToggleShowAll() {
    const next = !showAll;
    setShowAll(next);
    if (next && allAlerts === null) {
      try {
        const alerts = await api.monitoringAlerts({ limit: "50" });
        setAllAlerts(alerts);
      } catch {
        setAllAlerts([]);
      }
    }
  }

  return (
    <div className="relative" ref={containerRef}>
      <button
        onClick={() => setExpanded((v) => !v)}
        className="relative flex items-center text-muted-foreground hover:text-foreground"
        aria-label="Notifications"
      >
        <Bell className="size-4" />
        {unreadCount > 0 && (
          <span className="absolute -top-1.5 -right-1.5 bg-bearish text-white text-[9px] font-semibold rounded-full min-w-[14px] h-[14px] flex items-center justify-center px-1">
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>

      {expanded && (
        <div className="absolute right-0 top-full mt-2 w-80 max-h-96 overflow-y-auto rounded-md border border-border bg-card shadow-lg z-50 p-3">
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs font-semibold text-muted-foreground uppercase">Notifications</p>
            {unreadCount > 0 && (
              <button onClick={handleAcknowledgeAll} className="text-[10px] text-muted-foreground hover:text-foreground underline">
                Mark all as read
              </button>
            )}
          </div>

          {visibleUnread.length === 0 ? (
            <p className="text-xs text-muted-foreground">No unread alerts.</p>
          ) : (
            <div>
              {visibleUnread.map((a) => (
                <AlertRow key={a.id} alert={a} onAcknowledge={handleAcknowledge} />
              ))}
            </div>
          )}

          <button
            onClick={handleToggleShowAll}
            className="text-[10px] text-muted-foreground hover:text-foreground underline mt-3"
          >
            {showAll ? "Hide history" : "Show all"}
          </button>

          {showAll && (
            <div className="mt-2 border-t border-border pt-2">
              {allAlerts === null ? (
                <p className="text-xs text-muted-foreground">Loading…</p>
              ) : allAlerts.length === 0 ? (
                <p className="text-xs text-muted-foreground">No alerts yet.</p>
              ) : (
                allAlerts.map((a) => <AlertRow key={a.id} alert={a} onAcknowledge={handleAcknowledge} />)
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
