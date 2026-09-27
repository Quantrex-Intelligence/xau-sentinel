"use client";

import { Panel, PanelRow } from "@/components/layout/panel";
import { api } from "@/lib/api";
import { usePolling } from "@/lib/use-polling";
import { cn } from "@/lib/utils";

export default function SettingsPage() {
  const { data: settings } = usePolling(() => api.settings(), 15000);

  if (!settings) return null;

  return (
    <div className="p-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
      <Panel title="Market">
        <PanelRow label="Symbol">{settings.trading_symbol}</PanelRow>
        <PanelRow label="Session Timezone">{settings.session_timezone}</PanelRow>
        <PanelRow label="Data Mode">
          <span className={cn(settings.mode === "mock" ? "text-warning" : "text-bullish")}>
            {settings.mode.toUpperCase()}
          </span>
        </PanelRow>
      </Panel>

      <Panel title="Risk (informational only)">
        <PanelRow label="Account Balance">${settings.account_balance.toLocaleString()}</PanelRow>
        <PanelRow label="Risk / Trade">{settings.risk_per_trade_pct}%</PanelRow>
      </Panel>

      <Panel title="Analysis Thresholds">
        <PanelRow label="Swing Lookback">{settings.swing_lookback} bars</PanelRow>
        <PanelRow label="Displacement ATR ×">{settings.displacement_atr_mult}</PanelRow>
        <PanelRow label="Liquidity Sweep Buffer">{settings.liquidity_sweep_buffer_pips}</PanelRow>
        <PanelRow label="Equal Level Tolerance">{settings.equal_level_tolerance}</PanelRow>
        <PanelRow label="ATR Period">{settings.atr_period}</PanelRow>
        <PanelRow label="Retracement Range">
          {settings.retracement_min_pct}–{settings.retracement_max_pct}
        </PanelRow>
      </Panel>

      <Panel title="Data Integrity">
        <PanelRow label="Stale-Data Threshold">{settings.data_stale_seconds}s</PanelRow>
      </Panel>

      <p className="lg:col-span-2 text-xs text-muted-foreground">
        Read-only — these values come from the server&apos;s config.py / .env. Credentials
        (MT5 login, password, server) are never exposed to this UI.
      </p>
    </div>
  );
}
