"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, Database, Home, LayoutDashboard, Moon, Settings, SquareTerminal, Sun, Menu as MenuIcon, X } from "lucide-react";
import { useState, useSyncExternalStore } from "react";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Home", icon: Home, exact: true },
  { href: "/datasets", label: "Datasets", icon: Database },
  { href: "/sql", label: "SQL", icon: SquareTerminal },
  { href: "/charts", label: "Charts", icon: BarChart3 },
  { href: "/dashboards", label: "Dashboards", icon: LayoutDashboard },
];

function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2 px-2 py-1" aria-label="Facet home">
      <svg viewBox="0 0 24 24" className="size-6" aria-hidden>
        <rect x="2" y="2" width="20" height="20" rx="6" fill="var(--accent)" />
        <path d="M7 16.5V12M12 16.5V7.5M17 16.5v-6" stroke="var(--accent-fg)" strokeWidth="2.2" strokeLinecap="round" />
      </svg>
      <span className="text-[15px] font-semibold tracking-tight">Facet</span>
    </Link>
  );
}

function subscribeTheme(cb: () => void) {
  const obs = new MutationObserver(cb);
  obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => obs.disconnect();
}

function ThemeToggle() {
  const theme = useSyncExternalStore(
    subscribeTheme,
    () => document.documentElement.dataset.theme ?? "light",
    () => null,
  );
  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("facet-theme", next);
    } catch {
      /* private mode */
    }
  };
  return (
    <button
      onClick={toggle}
      className="flex h-8 w-full items-center gap-2.5 rounded-md px-2 text-[13px] text-muted hover:bg-surface-2 hover:text-fg"
      aria-label="Toggle colour theme"
    >
      {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
      {theme === "dark" ? "Light mode" : "Dark mode"}
    </button>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [lastPath, setLastPath] = useState(pathname);
  if (lastPath !== pathname) {
    // Close the mobile drawer on navigation (state derived during render, not in an effect).
    setLastPath(pathname);
    setOpen(false);
  }
  const isActive = (href: string, exact?: boolean) => (exact ? pathname === href : pathname === href || pathname.startsWith(`${href}/`));

  const nav = (
    <nav className="flex flex-1 flex-col gap-0.5 px-2" aria-label="Main">
      {NAV.map(({ href, label, icon: Icon, exact }) => {
        const active = isActive(href, exact);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex h-8 items-center gap-2.5 rounded-md px-2 text-[13px] font-medium transition-colors",
              active ? "bg-surface-2 text-fg shadow-[inset_0_0_0_1px_var(--border)]" : "text-muted hover:bg-surface-2 hover:text-fg",
            )}
          >
            <Icon className={cn("size-4", active ? "text-accent" : "")} />
            {label}
          </Link>
        );
      })}
    </nav>
  );

  const footer = (
    <div className="flex flex-col gap-0.5 border-t border-border p-2">
      <Link
        href="/settings"
        aria-current={isActive("/settings") ? "page" : undefined}
        className={cn(
          "flex h-8 items-center gap-2.5 rounded-md px-2 text-[13px] font-medium",
          isActive("/settings") ? "bg-surface-2 text-fg" : "text-muted hover:bg-surface-2 hover:text-fg",
        )}
      >
        <Settings className="size-4" /> Settings &amp; help
      </Link>
      <ThemeToggle />
    </div>
  );

  return (
    <>
      <button
        className="fixed top-2.5 left-2.5 z-40 rounded-md border border-border bg-surface p-1.5 shadow-sm md:hidden"
        onClick={() => setOpen(true)}
        aria-label="Open navigation"
      >
        <MenuIcon className="size-4" />
      </button>
      {open ? <div className="fixed inset-0 z-40 bg-black/30 md:hidden" onClick={() => setOpen(false)} /> : null}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex w-56 shrink-0 flex-col border-r border-border bg-surface transition-transform md:static md:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex h-14 items-center justify-between px-2">
          <Logo />
          <button className="rounded-md p-1 text-muted md:hidden" onClick={() => setOpen(false)} aria-label="Close navigation">
            <X className="size-4" />
          </button>
        </div>
        <div className="px-4 pt-2 pb-1.5 text-[11px] font-medium tracking-wide text-subtle uppercase">Workspace</div>
        {nav}
        {footer}
      </aside>
    </>
  );
}
