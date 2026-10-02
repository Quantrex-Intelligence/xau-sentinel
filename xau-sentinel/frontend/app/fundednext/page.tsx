"use client";

import { useState } from "react";
import { Panel, PanelRow } from "@/components/layout/panel";
import { Badge } from "@/components/ui/badge";
import { SafetyBanner } from "@/components/fundednext/safety-banner";
import { LimitBar } from "@/components/fundednext/limit-bar";
import { AccountSelector } from "@/components/fundednext/account-selector";
import { api } from "@/lib/api";
import { usePolling } from "@/lib/use-polling";
import { formatPrice } from "@/lib/format";

export default function FundedNextPage() {
  const [refreshKey, setRefreshKey] = useState(0);
  const { data: status } = usePolling(() => api.fundedNextStatus(), 5000, [refreshKey]);
  const { data: settings } = usePolling(() => api.fundedNextSettings(), 5000, [refreshKey]);

  function refetch() {
    setRefreshKey((k) => k + 1);
  }

  if (!status || !settings) return null;

  return (
    <div className="p-4 flex flex-col gap-4">
      <h1 className="text-lg font-semibold text-foreground tracking-tight">FundedNext</h1>
      <div className="flex items-center gap-2">
        <Badge variant={status.mode === "mock" ? "warning" : "bullish"}>{status.mode.toUpperCase()}</Badge>
        <span className="text-sm text-muted-foreground">
          Read-only monitoring. This app never places, closes, or modifies orders.
        </span>
      </div>

      <SafetyBanner level={status.safety_level} reason={status.reason} />

      {!status.data_available ? (
        <Panel title="Account Data">
          <p className="text-sm text-muted-foreground">
            Account data unavailable — {status.reason}. Values will appear once MT5 is connected
            (or switch MODE=mock to explore with synthetic data).
          </p>
        </Panel>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Panel title="Account">
            <PanelRow label="Balance">{formatPrice(status.balance)}</PanelRow>
            <PanelRow label="Equity">{formatPrice(status.equity)}</PanelRow>
            <PanelRow label="Today's P/L">
              <span className={(status.today_pnl ?? 0) >= 0 ? "text-bullish" : "text-bearish"}>
                {status.today_pnl !== null ? `${status.today_pnl >= 0 ? "+" : ""}${status.today_pnl.toFixed(2)}` : "—"}
              </span>
            </PanelRow>
            {status.profit_target !== null && (
              <>
                <PanelRow label="Profit Target">{formatPrice(status.profit_target)} ({status.profit_target_pct}%)</PanelRow>
                <PanelRow label="Progress">{status.progress_to_target_pct}%</PanelRow>
              </>
            )}
          </Panel>

          <Panel title="Loss Limits">
            <div className="space-y-4">
              {status.daily_loss_floor !== null && (
                <LimitBar
                  title="Daily Loss Limit"
                  floor={status.daily_loss_floor}
                  remaining={status.daily_loss_remaining ?? 0}
                  usedPct={status.daily_loss_used_pct ?? 0}
                />
              )}
              {status.max_loss_floor !== null && (
                <LimitBar
                  title="Maximum Loss Limit (static)"
                  floor={status.max_loss_floor}
                  remaining={status.max_drawdown_remaining ?? 0}
                  usedPct={status.max_drawdown_used_pct ?? 0}
                />
              )}
            </div>
          </Panel>

          <Panel title="Trading Requirements">
            {status.trading_days_required !== null ? (
              <PanelRow label="Trading Days">
                {status.trading_days_completed} / {status.trading_days_required}
              </PanelRow>
            ) : (
              <p className="text-xs text-muted-foreground">No minimum trading-day requirement in this phase.</p>
            )}
            {status.consistency_enabled ? (
              <PanelRow label="Consistency (largest day)">
                {status.largest_day_pct_of_profit !== null ? `${status.largest_day_pct_of_profit}%` : "—"} / {status.consistency_limit_pct}% limit
              </PanelRow>
            ) : (
              <p className="text-xs text-muted-foreground mt-2">
                Consistency rule not active (Stellar CFD accounts have none by default — only via the
                On-Demand Rewards add-on).
              </p>
            )}
          </Panel>

          <Panel title="Violations">
            {status.violations.length === 0 ? (
              <p className="text-xs text-muted-foreground">No active violations.</p>
            ) : (
              <div className="space-y-2">
                {status.violations.map((v, i) => (
                  <div key={i} className="text-sm">
                    <Badge
                      variant={v.level === "BREACHED" || v.level === "CRITICAL" ? "bearish" : "warning"}
                      className="mr-2"
                    >
                      {v.level}
                    </Badge>
                    <span className="text-foreground">{v.rule}</span>
                    <p className="text-xs text-muted-foreground mt-0.5">{v.message}</p>
                  </div>
                ))}
              </div>
            )}
          </Panel>
        </div>
      )}

      <AccountSelector settings={settings} onChanged={refetch} />
    </div>
  );
}
