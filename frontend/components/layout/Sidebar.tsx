"use client";

import Link, { useLinkStatus } from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ChevronDown, HelpCircle, Loader2, LogOut, Palette, ShieldCheck, UserRound, X } from "lucide-react";
import { NAV_SECTIONS, isVisible, navHref } from "@/lib/nav";
import { useRole } from "@/components/shell/RoleProvider";
import { useAuth } from "@/hooks/useAuth";

export function Sidebar({
  mobileOpen,
  onMobileClose,
}: {
  mobileOpen: boolean;
  onMobileClose: () => void;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const isOverview = pathname === "/" || pathname === "/overview/governance" || pathname === "/my-workspace" || ["/source-library", "/source-bundles", "/accounting-ontology", "/jurisdiction-rollout", "/risk-policy", "/evaluation-gates", "/model-prompt-registry"].includes(pathname);
  const { role, roleReady } = useRole();
  const { signOut, user, profile } = useAuth();
  // Prefer the provisioned profile's name (the real DB row) over Supabase's
  // user_metadata, which is only what the signup form stashed and can drift
  // once a tenant admin edits the profile.
  const displayName = profile?.full_name || user?.user_metadata?.full_name || user?.email || "User";
  const initials = (profile?.full_name || user?.user_metadata?.full_name || user?.email || "U")
    .split(/\s|@/)
    .slice(0, 2)
    .map((part: string) => part[0]?.toUpperCase())
    .join("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [identityOpen, setIdentityOpen] = useState(false);

  async function handleLogout() {
    await signOut();
    router.push("/login");
  }

  const visibleSections = NAV_SECTIONS.filter((section) => isVisible(section.allowedRoles, role)).map((section) => ({
    ...section,
    items: section.items.filter((item) => isVisible(item.allowedRoles, role)),
  }));

  useEffect(() => {
    onMobileClose();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  function toggle(id: string, open: boolean) {
    setExpanded((prev) => ({ ...prev, [id]: !open }));
  }

  const navContent = (
    <>
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

      {isOverview && <div className="rounded-lg border border-line bg-soft p-3"><p className="text-[9px] font-bold uppercase tracking-[.14em] text-muted">Pinned shortcuts</p><div className="mt-2 flex gap-2"><Link href="/ask-kriton" className="flex-1 rounded border border-line px-2 py-2 text-center text-[11px] text-ink">✦ Ask Kriton</Link><Link href="/review-tasks" className="flex-1 rounded border border-line px-2 py-2 text-center text-[11px] text-ink">↗ Review Tasks</Link></div></div>}

      <nav className="flex-1 overflow-y-auto py-4 space-y-1" aria-busy={!roleReady}>
        {!roleReady && (
          <div className="space-y-2 px-3" aria-label="Loading menu">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="h-8 rounded-lg bg-soft animate-pulse" />
            ))}
          </div>
        )}
        {roleReady && visibleSections.map((section) => {
          const isOpen = expanded[section.id] ?? (section.id === "overview" || section.items.some((item) => navHref(item.slug) === pathname));
          return (
            <div key={section.id}>
              <button
                type="button"
                onClick={() => toggle(section.id, isOpen)}
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
                        aria-current={active ? "page" : undefined}
                        onNavigate={onMobileClose}
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
                        <NavigationHint label={item.label} />
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
        {identityOpen && <div className="mb-2 space-y-0.5 rounded-xl border border-line bg-panel p-1.5 shadow-lg">
          <Link href="/my-workspace" className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-ink hover:bg-soft"><UserRound size={15} /> Profile & My Workspace</Link>
          <Link href="/account/security" className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-ink hover:bg-soft"><ShieldCheck size={15} /> Account security</Link>
          <Link href="/settings?tab=appearance" className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-ink hover:bg-soft"><Palette size={15} /> Appearance & accessibility</Link>
          <Link href="/support-tickets" className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-ink hover:bg-soft"><HelpCircle size={15} /> Help</Link>
          <button onClick={handleLogout} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-bad hover:bg-bad/10"><LogOut size={15} /> Log out</button>
        </div>}
        <button onClick={() => setIdentityOpen((value) => !value)} aria-expanded={identityOpen} className="flex min-h-12 w-full items-center gap-3 rounded-xl border border-line px-3 text-left hover:bg-soft">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand/10 text-xs font-bold text-brand">{initials}</span>
          <span className="min-w-0 flex-1"><span className="block truncate text-sm font-semibold text-ink">{displayName}</span><span className="block truncate text-xs text-muted">{role}</span></span>
          <span aria-hidden="true">›</span>
        </button>
      </div>
    </>
  );

  return (
    <>
      <aside className="hidden lg:flex w-72 shrink-0 flex-col border-r border-line bg-panel h-screen sticky top-0 p-3.5">
        {navContent}
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={onMobileClose} />
          <aside className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col bg-panel p-3.5 shadow-2xl">
            <button
              onClick={onMobileClose}
              aria-label="Close menu"
              className="mb-2 flex h-9 w-9 items-center justify-center self-end rounded-lg text-muted hover:bg-soft"
            >
              <X size={18} />
            </button>
            {navContent}
          </aside>
        </div>
      )}
    </>
  );
}

/** Uses Next's navigation lifecycle, including cancellation and back/forward. */
function NavigationHint({ label }: { label: string }) {
  const { pending } = useLinkStatus();
  return <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-line bg-chip text-[11px] text-muted">
    {pending ? <><Loader2 size={12} className="animate-spin" aria-hidden="true" /><span role="status" className="sr-only">Opening {label}…</span></> : <span aria-hidden="true">›</span>}
  </span>;
}
