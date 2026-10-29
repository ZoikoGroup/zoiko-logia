"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import { ArrowLeftRight, ChevronDown, Menu, Search, X } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { humanize } from "@/components/operations/ui";
import { usePlatformCommand } from "@/components/platform/command";
import { NAV, navCounts, type NavCount } from "@/components/platform/sections";

/** Super Admin control plane shell (Dashboard & Sidebar decision record):
 * its own sidebar and a permanent "Global platform" context, so it is never
 * mistaken for a tenant workspace. The sidebar follows the ZoikoLogia
 * command-center design; every entry is a platform page
 * (components/platform/sections), never a tenant workspace page. */

/** The sidebar with live counts: only for a platform Super Admin, so nobody
 * else's view calls the platform API (the pages themselves refuse them). */
function LiveSuperAdminNav() {
  const { data } = usePlatformCommand();
  return <SuperAdminNav counts={data ? navCounts(data) : {}} />;
}

function SuperAdminNav({ counts = {} }: { counts?: Record<string, NavCount> }) {
  const pathname = usePathname();
  const row = "flex min-h-9 items-center gap-2.5 rounded-lg px-3 py-2 text-sm";

  return (
    <>
      <Link href="/super-admin" className="flex h-[68px] shrink-0 items-center bg-white px-5" aria-label="ZoikoLogia Super Admin">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/brand/zoikologia-logo.png" alt="ZoikoLogia" width={393} height={69} className="h-auto w-[210px]" />
      </Link>
      <nav className="flex-1 space-y-4 overflow-y-auto px-2.5 py-4" aria-label="Super Admin">
        <p className="px-3 text-[11px] font-bold uppercase tracking-[0.14em] text-white/70">Platform control plane</p>
        {NAV.map(({ section, items }) => (
          <div key={section}>
            <p className="px-3 pb-1.5 text-[11px] font-bold uppercase tracking-[0.14em] text-white/70">{section}</p>
            {items.map(({ label, icon: Icon, href }) => {
              const active = pathname === href;
              const live = counts[href];
              return (
                <Link key={label} href={href} aria-current={active ? "page" : undefined}
                  className={`${row} ${active ? "bg-accent font-semibold text-hero shadow-[0_6px_16px_rgba(242,140,40,0.35)]" : "text-white/90 hover:bg-white/10"}`}>
                  <Icon size={16} /> <span className="flex-1">{label}</span>
                  {live && (
                    <span aria-label={`${live.count}${live.attention ? " needing attention" : ""}`}
                      className={`min-w-5 rounded-full px-1.5 text-center text-[11px] font-bold leading-5 ${active
                        ? "bg-hero/15 text-hero" : live.attention ? "bg-accent text-hero" : "bg-white/15 text-white/80"}`}>
                      {live.count}
                    </span>
                  )}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>
      <div className="p-2.5">
        <Link href="/" className="flex min-h-11 items-center gap-2 rounded-lg border border-white/15 px-3 text-sm font-semibold text-white hover:bg-white/10">
          <ArrowLeftRight size={16} /> Switch to my workspace
        </Link>
      </div>
    </>
  );
}

/** One fixed scope, shown in the design's select style. */
function ScopeChip({ children }: { children: ReactNode }) {
  return (
    <span className="hidden h-11 items-center gap-6 rounded-lg border border-line bg-panel px-4 text-sm font-semibold text-ink md:inline-flex">
      {children} <ChevronDown size={16} className="text-muted" />
    </span>
  );
}

export function SuperAdminChrome({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { profile } = useAuth();
  // The drawer belongs to the page it was opened on, so navigating closes it.
  const [openedOn, setOpenedOn] = useState<string | null>(null);
  const mobileOpen = openedOn === pathname;
  const setMobileOpen = (open: boolean) => setOpenedOn(open ? pathname : null);
  const name = profile?.full_name || profile?.email || "Super Admin";
  const isSuperAdmin = profile?.platform_role === "super_admin";
  const nav = isSuperAdmin ? <LiveSuperAdminNav /> : <SuperAdminNav />;
  const initials = name.split(/\s|@/).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("");

  return (
    <div className="platform-light flex min-h-screen w-full min-w-0 bg-bg text-ink">
      <aside className="sticky top-0 hidden h-screen w-[264px] shrink-0 flex-col bg-hero lg:flex">
        {nav}
      </aside>
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col bg-hero shadow-2xl">
            <button onClick={() => setMobileOpen(false)} aria-label="Close menu"
              className="absolute right-2 top-4 z-10 grid h-9 w-9 place-items-center rounded-lg text-hero hover:bg-soft"><X size={18} /></button>
            {nav}
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-[68px] items-center gap-3 border-b border-line bg-panel/95 px-4 backdrop-blur lg:px-6">
          <button onClick={() => setMobileOpen(true)} aria-label="Open menu"
            className="grid h-10 w-10 place-items-center rounded-lg text-ink hover:bg-soft lg:hidden"><Menu size={20} /></button>
          <label className="relative hidden w-full max-w-[470px] sm:block">
            <span className="sr-only">Search</span>
            <Search size={16} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
            <input type="search" placeholder="Search controls, decisions, services..." title="Search is not available yet" disabled
              className="h-11 w-full rounded-lg border border-line bg-soft pl-10 pr-3 text-sm text-ink placeholder:text-muted disabled:cursor-not-allowed" />
          </label>
          <ScopeChip>Global platform</ScopeChip>
          <span className="hidden text-xs text-muted 2xl:inline">Platform metadata only · no tenant content</span>
          <div className="ml-auto flex items-center gap-3">
            <span className="grid h-9 w-9 place-items-center rounded-full bg-accent text-xs font-bold text-white">{initials}</span>
            <span className="hidden min-w-0 sm:block">
              <span className="block truncate text-sm font-semibold text-ink">{name}</span>
              <span className="block text-xs text-muted">{profile?.platform_role ? `Platform ${humanize(profile.platform_role).toLowerCase()}` : "No platform role"}</span>
            </span>
          </div>
        </header>
        {children}
      </div>
    </div>
  );
}
