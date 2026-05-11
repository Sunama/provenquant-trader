"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart2, Bot, Eye, LayoutDashboard, Settings, X } from "lucide-react";
import { cn } from "@/lib/utils";

const nav = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/strategies", label: "Strategies", icon: Bot },
  { href: "/watched-assets", label: "Watched Assets", icon: Eye },
  { href: "/analytics", label: "Analytics", icon: BarChart2 },
  { href: "/settings", label: "Settings", icon: Settings },
];

interface SidebarProps {
  isOpen?: boolean;
  onClose?: () => void;
}

export function Sidebar({ isOpen, onClose }: SidebarProps) {
  const pathname = usePathname();

  return (
    <aside
      className={cn(
        "fixed inset-y-0 left-0 z-50 flex h-screen w-56 flex-col border-r bg-sidebar px-3 py-4",
        "transition-transform duration-300 ease-in-out",
        "md:static md:z-auto md:translate-x-0",
        isOpen ? "translate-x-0" : "-translate-x-full"
      )}
    >
      <div className="relative mb-6 px-2">
        <span className="text-lg font-bold tracking-tight text-sidebar-foreground">
          ProvenQuant
        </span>
        <span className="ml-1 text-xs text-muted-foreground">Trader</span>
        <button
          className="absolute right-0 top-0.5 md:hidden"
          onClick={onClose}
          aria-label="Close menu"
        >
          <X className="h-4 w-4 text-sidebar-foreground" />
        </button>
      </div>

      <nav className="flex flex-col gap-1">
        {nav.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            onClick={onClose}
            className={cn(
              "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
              pathname === href || (href !== "/" && pathname.startsWith(href))
                ? "bg-sidebar-accent text-sidebar-accent-foreground"
                : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
            )}
          >
            <Icon className="h-4 w-4" />
            {label}
          </Link>
        ))}
      </nav>
    </aside>
  );
}
