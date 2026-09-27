import { cn } from "@/lib/utils";

export function Panel({
  title,
  children,
  className,
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("rounded-md border border-border bg-card p-4", className)}>
      <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase mb-3">
        {title}
      </h3>
      {children}
    </div>
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
