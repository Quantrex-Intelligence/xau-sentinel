import { cn } from "@/lib/utils";
import { formatPrice } from "@/lib/format";
import type { FundedNextTradeSnapshot } from "@/lib/types";

const ACCOUNT_LABELS: Record<string, string> = {
  stellar_2step: "Stellar 2-Step",
  stellar_lite: "Stellar Lite",
};

const LEVEL_TEXT: Record<string, string> = {
  SAFE: "text-bullish", WARNING: "text-warning", CRITICAL: "text-bearish",
  BREACHED: "text-bearish", UNKNOWN: "text-muted-foreground",
};

/** Renders the FundedNext account/risk state captured at the moment this
 * trade was recorded — a frozen snapshot, never the account's current
 * state. The "AT ENTRY" label and captured_at timestamp exist specifically
 * so this is never mistaken for a live figure. */
export function FundedNextContextCard({ snapshot }: { snapshot: FundedNextTradeSnapshot | null }) {
  if (!snapshot) {
    return (
      <div className="rounded border border-border p-3">
        <p className="text-[11px] font-semibold text-muted-foreground mb-1">FUNDEDNEXT CONTEXT AT ENTRY</p>
        <p className="text-xs text-muted-foreground">Not captured for this trade.</p>
      </div>
    );
  }

  if (!snapshot.data_available) {
    return (
      <div className="rounded border border-border p-3">
        <p className="text-[11px] font-semibold text-muted-foreground mb-1">FUNDEDNEXT CONTEXT AT ENTRY</p>
        <p className="text-xs text-muted-foreground">
          UNKNOWN / DATA UNAVAILABLE at entry — {snapshot.reason ?? "no reason recorded"}
        </p>
      </div>
    );
  }

  return (
    <div className="rounded border border-border p-3">
      <div className="flex items-center justify-between mb-2">
        <p className="text-[11px] font-semibold text-muted-foreground">FUNDEDNEXT CONTEXT AT ENTRY</p>
        <span
          className={cn(
            "text-[10px] font-semibold uppercase",
            LEVEL_TEXT[snapshot.safety_level ?? "UNKNOWN"]
          )}
        >
          {snapshot.safety_level}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-1.5 text-xs">
        <Field label="Account" value={ACCOUNT_LABELS[snapshot.account_type ?? ""] ?? snapshot.account_type ?? "—"} />
        <Field label="Phase" value={snapshot.phase ?? "—"} />
        <Field label="Balance" value={formatPrice(snapshot.balance)} />
        <Field label="Equity" value={formatPrice(snapshot.equity)} />
        <Field label="Daily Loss Remaining" value={formatPrice(snapshot.daily_loss_remaining)} />
        <Field label="Max Drawdown Remaining" value={formatPrice(snapshot.max_drawdown_remaining)} />
        <Field
          label="Drawdown Used"
          value={snapshot.max_drawdown_used_pct !== null ? `${snapshot.max_drawdown_used_pct}%` : "—"}
        />
        <Field label="Mode" value={snapshot.mode ?? "—"} />
      </div>
      {snapshot.captured_at && (
        <p className="text-[10px] text-muted-foreground mt-2">
          Captured {snapshot.captured_at} — this is a frozen snapshot, not the account&apos;s current state.
        </p>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className="font-medium text-foreground">{value}</p>
    </div>
  );
}
