"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import {
  LayoutDashboard,
  LineChart,
  Target,
  BookText,
  BarChart3,
  ShieldAlert,
  Sparkles,
  Settings,
} from "lucide-react";

const NAV_ITEMS = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/market", label: "Market", icon: LineChart },
  { href: "/setups", label: "Setups", icon: Target },
  { href: "/fundednext", label: "FundedNext", icon: ShieldAlert },
  { href: "/journal", label: "Journal", icon: BookText },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/assistant", label: "AI Assistant", icon: Sparkles },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden md:flex w-56 shrink-0 flex-col border-r border-border bg-sidebar">
      <div className="h-14 flex items-center px-4 border-b border-border">
        <span className="text-sm font-semibold tracking-wide text-foreground">
          XAU SENTINEL
        </span>
      </div>
      <nav className="flex-1 py-2">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? pathname === "/" : pathname?.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-2.5 px-4 py-2 text-sm transition-colors",
                active
                  ? "text-foreground bg-accent border-l-2 border-info -ml-px"
                  : "text-muted-foreground hover:text-foreground hover:bg-accent/50 border-l-2 border-transparent"
              )}
            >
              <Icon className="size-4" />
              {label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
