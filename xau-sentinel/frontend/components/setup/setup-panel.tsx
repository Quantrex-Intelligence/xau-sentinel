import { Panel } from "@/components/layout/panel";
import { cn } from "@/lib/utils";
import { formatPrice } from "@/lib/format";
import type { Setup } from "@/lib/types";
import { Check } from "lucide-react";

const STATE_STYLES: Record<string, { text: string; dot: string }> = {
  "NO SETUP": { text: "text-muted-foreground", dot: "bg-muted-foreground" },
  DEVELOPING: { text: "text-warning", dot: "bg-warning" },
  VALID: { text: "text-bullish", dot: "bg-bullish" },
  INVALIDATED: { text: "text-bearish", dot: "bg-bearish" },
};

export function SetupPanel({ setup }: { setup: Setup | null }) {
  if (!setup) {
    return (
      <Panel title="Current Setup">
        <span className="text-xs text-muted-foreground">No data</span>
      </Panel>
    );
  }

  const style = STATE_STYLES[setup.state] ?? STATE_STYLES["NO SETUP"];

  return (
    <Panel title="Current Setup">
      <div className="flex items-center gap-2 mb-1">
        <span className={cn("size-2 rounded-full", style.dot)} />
        <span className={cn("text-lg font-bold tracking-wide", style.text)}>
          {setup.direction ? `${setup.direction} — ` : ""}
          {setup.state}
        </span>
      </div>
      <p className="text-xs text-muted-foreground mb-3">{setup.reason}</p>

      <div className="grid grid-cols-2 gap-x-4 gap-y-2 mb-3">
        {Object.entries(setup.checklist).map(([step, done]) => (
          <div key={step} className="flex items-center gap-2 text-sm">
            {done === true ? (
              <span className="flex items-center justify-center size-4 rounded-full bg-bullish/20 text-bullish shrink-0">
                <Check className="size-3" />
              </span>
            ) : (
              <span className="size-4 rounded-full border border-border shrink-0" />
            )}
            <span className={done === true ? "text-foreground" : "text-muted-foreground"}>{step}</span>
          </div>
        ))}
      </div>

      {setup.state === "VALID" && (
        <div className="grid grid-cols-2 gap-2 pt-3 border-t border-border text-sm">
          <PlanField label="Entry Zone" value={setup.entry_zone ? `${formatPrice(setup.entry_zone[0])}–${formatPrice(setup.entry_zone[1])}` : "—"} />
          <PlanField label="Stop Loss" value={formatPrice(setup.stop_loss)} />
          <PlanField label="Take Profit" value={formatPrice(setup.take_profit)} />
          <PlanField label="R:R" value={setup.rr ? `1:${setup.rr}` : "—"} />
        </div>
      )}
    </Panel>
  );
}

function PlanField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className="font-mono font-medium text-foreground">{value}</p>
    </div>
  );
}
