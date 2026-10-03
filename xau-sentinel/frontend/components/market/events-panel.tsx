"use client";

import { Disclosure } from "@/components/layout/disclosure";
import { api } from "@/lib/api";
import { usePolling } from "@/lib/use-polling";

export function EventsPanel() {
  const { data: events } = usePolling(() => api.events(8), 5000);
  const count = events?.length ?? 0;

  return (
    <Disclosure title="Recent events" summary={count ? `${count}` : "none yet"}>
      <div className="space-y-1.5">
        {events?.map((e) => (
          <div key={e.id} className="flex items-baseline gap-2 text-sm">
            <span className="text-xs font-mono text-muted-foreground shrink-0">{e.event_time.slice(11, 16)}</span>
            <span className="text-foreground">{e.description}</span>
          </div>
        ))}
      </div>
    </Disclosure>
  );
}
