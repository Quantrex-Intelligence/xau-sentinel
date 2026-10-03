import { Disclosure } from "@/components/layout/disclosure";
import { PanelRow } from "@/components/layout/panel";
import { formatPrice } from "@/lib/format";

export function ZonesPanel({ zones }: { zones: Record<string, number> }) {
  const entries = Object.entries(zones);
  return (
    <Disclosure title="Key zones" summary={entries.length ? `${entries.length} levels` : "none yet"}>
      {entries.map(([name, price]) => (
        <PanelRow key={name} label={name}>
          {formatPrice(price)}
        </PanelRow>
      ))}
    </Disclosure>
  );
}
