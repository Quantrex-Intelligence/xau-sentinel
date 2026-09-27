"use client";

import { Panel } from "@/components/layout/panel";
import { api } from "@/lib/api";
import { usePolling } from "@/lib/use-polling";
import { cn } from "@/lib/utils";

const LEVEL_STYLES: Record<string, string> = {
  valid: "text-bullish",
  developing: "text-warning",
  invalidated: "text-bearish",
};

export function AlertCenter() {
  const { data: alerts } = usePolling(() => api.alerts(8), 5000);

  return (
    <Panel title="Alerts">
      {!alerts || alerts.length === 0 ? (
        <span className="text-xs text-muted-foreground">No alerts yet this session.</span>
      ) : (
        <div className="space-y-2">
          {alerts.map((a) => (
            <div key={a.id} className="text-sm border-b border-border last:border-0 pb-2 last:pb-0">
              <div className="flex items-center gap-2">
                <span className={cn("text-xs font-mono text-muted-foreground")}>
                  {a.alert_time.slice(11, 19)}
                </span>
                <span className={cn("text-xs font-semibold uppercase", LEVEL_STYLES[a.level] ?? "text-foreground")}>
                  {a.level}
                </span>
              </div>
              <p className="text-foreground mt-0.5">{a.message}</p>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}
