"use client";

import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/** A collapsed-by-default section: one compact row with a title and a
 * short summary (e.g. a count). Expanding reveals the detail. Used so that
 * secondary analysis stays one click away instead of on screen. */
export function Disclosure({
  title,
  summary,
  children,
}: {
  title: string;
  summary?: string;
  children?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Card size="sm">
      <CardContent>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="flex w-full items-center justify-between gap-2 text-left text-sm"
        >
          <span className="flex items-baseline gap-2">
            <span className="font-medium text-foreground">{title}</span>
            {summary && <span className="text-xs text-muted-foreground">{summary}</span>}
          </span>
          <ChevronDown
            className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")}
          />
        </button>
        {open && children && <div className="mt-3">{children}</div>}
      </CardContent>
    </Card>
  );
}
