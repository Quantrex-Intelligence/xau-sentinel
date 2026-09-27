import { Panel, PanelRow } from "@/components/layout/panel";
import { formatPrice } from "@/lib/format";

export function ZonesPanel({ zones }: { zones: Record<string, number> }) {
  const entries = Object.entries(zones);
  return (
    <Panel title="Key Zones">
      {entries.length === 0 ? (
        <span className="text-xs text-muted-foreground">Not enough data yet.</span>
      ) : (
        <div>
          {entries.map(([name, price]) => (
            <PanelRow key={name} label={name}>
              {formatPrice(price)}
            </PanelRow>
          ))}
        </div>
      )}
    </Panel>
  );
}
