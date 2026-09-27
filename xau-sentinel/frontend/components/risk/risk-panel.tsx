import { Panel, PanelRow } from "@/components/layout/panel";
import { formatR } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Risk } from "@/lib/types";

export function RiskPanel({ risk }: { risk: Risk | null }) {
  if (!risk) {
    return (
      <Panel title="Risk">
        <span className="text-xs text-muted-foreground">No data</span>
      </Panel>
    );
  }

  return (
    <Panel title="Risk">
      <PanelRow label="Account Balance">${risk.balance.toLocaleString()}</PanelRow>
      <PanelRow label="Risk / Trade">{risk.risk_per_trade_pct.toFixed(2)}%</PanelRow>
      <PanelRow label="Today's P/L">
        <span className={cn(risk.today_r >= 0 ? "text-bullish" : "text-bearish")}>
          {formatR(risk.today_r)}
        </span>
      </PanelRow>
      <p className="mt-3 text-xs text-muted-foreground">
        Informational only — this app never sizes or places trades.
      </p>
    </Panel>
  );
}
