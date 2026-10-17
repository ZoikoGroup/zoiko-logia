"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import { ArrowLeftRight, Building2, Globe2, LayoutGrid, Menu, Users, X } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { BrandMark } from "@/components/layout/AppHeader";

/** Super Admin control plane shell (Dashboard & Sidebar decision record):
 * its own sidebar and a permanent "Global platform" context badge, so it is
 * never mistaken for a tenant workspace. The sidebar lists platform pages
 * only; each designed destination is added here once its platform-wide
 * version is built, never as a link into a tenant workspace page. */

function SuperAdminNav() {
  const pathname = usePathname();
  const linkClass = (active: boolean) => `flex items-center justify-between gap-3 rounded-lg px-3 py-2 text-sm ${active
    ? "bg-accent font-semibold text-hero" : "text-white/85 hover:bg-white/10"}`;

  return (
    <>
      <div className="mb-3 flex items-center gap-3 border-b border-white/10 px-2 pb-4">
        <BrandMark className="h-10 w-10" />
        <div className="min-w-0">
          <div className="truncate text-lg font-extrabold tracking-tight text-white">ZoikoLogia</div>
          <div className="text-[11px] font-bold uppercase tracking-[0.14em] text-accent">Platform control plane</div>
        </div>
      </div>
      <nav className="flex-1 space-y-4 overflow-y-auto pb-4" aria-label="Super Admin">
        <div>
          <p className="px-3 pb-1 text-[11px] font-bold uppercase tracking-[0.14em] text-white/55">Platform command</p>
          <Link href="/super-admin" className={linkClass(pathname === "/super-admin")} aria-current={pathname === "/super-admin" ? "page" : undefined}>
            <span className="flex items-center gap-2.5"><LayoutGrid size={16} /> Super Admin Command</span>
          </Link>
        </div>
        <div>
          <p className="px-3 pb-1 text-[11px] font-bold uppercase tracking-[0.14em] text-white/55">Directory</p>
          {[
            { href: "/super-admin/companies", label: "Companies", icon: Building2 },
            { href: "/super-admin/accounts", label: "Accounts", icon: Users },
          ].map(({ href, label, icon: Icon }) => (
            <Link key={href} href={href} className={linkClass(pathname === href)} aria-current={pathname === href ? "page" : undefined}>
              <span className="flex items-center gap-2.5"><Icon size={16} /> {label}</span>
            </Link>
          ))}
        </div>
      </nav>
      <Link href="/" className="flex min-h-11 items-center gap-2 rounded-lg border border-white/15 px-3 text-sm font-semibold text-white hover:bg-white/10">
        <ArrowLeftRight size={16} /> Switch to my workspace
      </Link>
    </>
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
  const initials = name.split(/\s|@/).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("");

  return (
    <>
      <aside className="sticky top-0 hidden h-screen w-72 shrink-0 flex-col bg-hero p-3.5 lg:flex">
        <SuperAdminNav />
      </aside>
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col bg-hero p-3.5 shadow-2xl">
            <button onClick={() => setMobileOpen(false)} aria-label="Close menu"
              className="mb-2 grid h-9 w-9 place-items-center self-end rounded-lg text-white/80 hover:bg-white/10"><X size={18} /></button>
            <SuperAdminNav />
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex min-h-16 items-center gap-3 border-b border-line bg-panel/95 px-4 backdrop-blur">
          <button onClick={() => setMobileOpen(true)} aria-label="Open menu"
            className="grid h-10 w-10 place-items-center rounded-lg text-ink hover:bg-soft lg:hidden"><Menu size={20} /></button>
          <span className="inline-flex items-center gap-2 rounded-lg border-2 border-accent bg-accent/10 px-3 py-1.5 text-sm font-bold text-accent-ink">
            <Globe2 size={16} /> Global platform
          </span>
          <span className="hidden text-xs text-muted sm:inline">Platform metadata only · no tenant content</span>
          <div className="ml-auto flex items-center gap-3">
            <span className="grid h-9 w-9 place-items-center rounded-full bg-accent text-xs font-bold text-hero">{initials}</span>
            <span className="hidden min-w-0 sm:block">
              <span className="block truncate text-sm font-semibold text-ink">{name}</span>
              <span className="block text-xs text-muted">Platform Super Admin</span>
            </span>
          </div>
        </header>
        {children}
      </div>
    </>
  );
}
