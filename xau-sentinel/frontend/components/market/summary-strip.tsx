import { Panel } from "@/components/layout/panel";
import { StateBadge } from "@/components/market/structure-badge";
import { Badge } from "@/components/ui/badge";
import { formatPrice } from "@/lib/format";
import type { Regime, Setup, Structure, Timeframe } from "@/lib/types";

type Bias = { label: string; tone: "bullish" | "bearish" | "secondary"; basis: string };

const SETUP_TONE: Record<string, "bullish" | "bearish" | "warning" | "secondary"> = {
  VALID: "bullish",
  DEVELOPING: "warning",
  INVALIDATED: "bearish",
  "NO SETUP": "secondary",
};

/** Deterministic bias read from existing fields only -- never an LLM
 * judgment. A directional setup wins; otherwise H1 structure, the primary
 * timeframe per the methodology. */
export function deriveBias(setup: Setup | null, structure: Partial<Record<Timeframe, Structure>>): Bias {
  if (setup?.direction === "BUY") return { label: "Bullish", tone: "bullish", basis: `setup ${setup.state.toLowerCase()}` };
  if (setup?.direction === "SELL") return { label: "Bearish", tone: "bearish", basis: `setup ${setup.state.toLowerCase()}` };
  const h1 = structure.H1?.state;
  if (h1 === "BULLISH") return { label: "Bullish", tone: "bullish", basis: "H1 structure" };
  if (h1 === "BEARISH") return { label: "Bearish", tone: "bearish", basis: "H1 structure" };
  return { label: "No clear bias", tone: "secondary", basis: h1 ? `H1 ${h1.toLowerCase()}` : "no H1 data" };
}

export function SummaryPanel({
  structure,
  regime,
  setup,
}: {
  structure: Partial<Record<Timeframe, Structure>>;
  regime: Regime | null;
  setup: Setup | null;
}) {
  const bias = deriveBias(setup, structure);
  const showPlan = setup?.state === "VALID";

  return (
    <Panel title="Summary">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex items-center gap-2">
          <Badge variant={bias.tone}>{bias.label}</Badge>
          <span className="text-xs text-muted-foreground">from {bias.basis}</span>
        </div>
        {regime && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            Regime <StateBadge state={regime.regime} />
          </div>
        )}
        {setup && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            Setup <Badge variant={SETUP_TONE[setup.state] ?? "secondary"}>{setup.state}</Badge>
          </div>
        )}
      </div>

      {showPlan && setup && (
        <div className="mt-4 grid grid-cols-4 gap-3 text-sm">
          <Plan label="Entry" value={setup.entry_zone ? `${formatPrice(setup.entry_zone[0])}–${formatPrice(setup.entry_zone[1])}` : "—"} />
          <Plan label="Stop" value={formatPrice(setup.stop_loss)} />
          <Plan label="Target" value={formatPrice(setup.take_profit)} />
          <Plan label="R:R" value={setup.rr ? `1:${setup.rr}` : "—"} />
        </div>
      )}
    </Panel>
  );
}

function Plan({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="font-mono font-medium text-foreground">{value}</p>
    </div>
  );
}
