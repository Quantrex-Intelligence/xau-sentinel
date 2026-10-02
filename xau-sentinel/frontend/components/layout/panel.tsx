import { Card, CardHeader, CardTitle, CardContent, CardAction } from "@/components/ui/card";

/**
 * Shared panel chrome for every dashboard section. Wraps the shadcn Card
 * primitives so every call site (21 files, title+children only, no
 * className overrides as of the 2026-10 redesign) gets Card's elevation/
 * radius/spacing for free. `action`/`density` are additive and optional.
 */
export function Panel({
  title,
  action,
  density = "default",
  children,
  className,
}: {
  title: string;
  action?: React.ReactNode;
  density?: "default" | "compact";
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Card size={density === "compact" ? "sm" : "default"} className={className}>
      <CardHeader>
        <CardTitle className="text-sm font-semibold">{title}</CardTitle>
        {action && <CardAction>{action}</CardAction>}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

export function PanelRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-1.5 text-sm border-b border-border last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium text-foreground font-mono tabular-nums">{children}</span>
    </div>
  );
}
