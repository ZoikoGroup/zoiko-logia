"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ChevronDown, LogOut } from "lucide-react";
import { NAV_SECTIONS, isVisible, navHref } from "@/lib/nav";
import { useRole } from "@/components/shell/RoleProvider";

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { role } = useRole();
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  function handleLogout() {
    document.cookie = "zoiko_auth=; path=/; max-age=0";
    router.push("/login");
  }

  const visibleSections = NAV_SECTIONS.filter((section) => isVisible(section.allowedRoles, role)).map((section) => ({
    ...section,
    items: section.items.filter((item) => isVisible(item.allowedRoles, role)),
  }));

  useEffect(() => {
    const active = visibleSections.find((section) => section.items.some((item) => navHref(item.slug) === pathname));
    if (active) {
      setExpanded((prev) => new Set(prev).add(active.id));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname, role]);

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <aside className="hidden lg:flex w-72 shrink-0 flex-col border-r border-line bg-panel h-screen sticky top-0 p-3.5">
      <div className="flex items-center gap-3.5 px-2 pb-5 mb-2 border-b border-line">
        <div className="shrink-0 p-3 rounded-2xl bg-gradient-to-br from-brand/15 to-gold/15 border border-brand/20">
          <svg viewBox="0 0 64 64" className="h-11 w-11" role="img" aria-label="ZoikoLogia logo">
            <rect x="4" y="4" width="56" height="56" rx="16" fill="#16799A" />
            <rect x="17" y="18" width="31" height="30" rx="2" fill="none" stroke="#fff" strokeWidth="4" />
            <rect x="24" y="25" width="5" height="16" fill="#F3C437" />
            <rect x="32" y="25" width="5" height="16" fill="#F3C437" />
            <rect x="40" y="25" width="5" height="16" fill="#F3C437" />
          </svg>
        </div>
        <div className="min-w-0">
          <div className="text-xl font-extrabold text-ink tracking-tight truncate">ZoikoLogia</div>
          <div className="text-xs text-muted truncate mt-0.5">Governance</div>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto py-4 space-y-1">
        {visibleSections.map((section) => {
          const isOpen = expanded.has(section.id);
          return (
            <div key={section.id}>
              <button
                type="button"
                onClick={() => toggle(section.id)}
                aria-expanded={isOpen}
                aria-controls={`nav-section-${section.id}`}
                className="w-full flex items-start justify-between gap-2 px-3 py-2.5 rounded-lg text-sm font-bold tracking-wide uppercase text-ink hover:bg-soft text-left"
              >
                <span className="text-left leading-snug">{section.label}</span>
                <ChevronDown size={16} className={`shrink-0 mt-0.5 transition-transform ${isOpen ? "rotate-180" : ""}`} />
              </button>
              {isOpen && (
                <div id={`nav-section-${section.id}`} className="space-y-0.5 mt-0.5 mb-2">
                  {section.items.map((item) => {
                    const href = navHref(item.slug);
                    const active = pathname === href;
                    return (
                      <Link
                        key={item.slug}
                        href={href}
                        className={`flex items-center justify-between gap-3 rounded-xl px-3 py-2.5 text-sm border ${
                          active
                            ? "text-ink bg-gradient-to-r from-brand/15 to-gold/10 border-brand/30 shadow-[inset_3px_0_0_0_var(--color-brand)]"
                            : "text-ink border-transparent hover:bg-soft"
                        }`}
                      >
                        <span className="flex items-center gap-2.5 min-w-0">
                          <item.icon size={16} />
                          <span className="truncate">{item.label}</span>
                        </span>
                        <span className="shrink-0 text-[11px] rounded-full border border-line bg-chip text-muted px-1.5 py-0.5">
                          ›
                        </span>
                      </Link>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </nav>

      <div className="pt-3 mt-1 border-t border-line">
        <button
          onClick={handleLogout}
          className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl border border-line text-sm font-medium text-ink hover:bg-bad/10 hover:border-bad/30 hover:text-bad transition-colors"
        >
          <LogOut size={16} />
          Sign out
        </button>
      </div>
    </aside>
  );
}
