"use client";

import type { ReactNode } from "react";
import { ShieldX } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useLiveData } from "@/components/overview/useLiveData";
import { Badge, EmptyState } from "@/components/operations/ui";
import {
  getPlatformDirectory, type PlatformAccount, type PlatformAccountStatus, type PlatformCompany,
} from "@/lib/api";

/** Shared pieces of the Super Admin Companies and Accounts pages. */

/** Renders the page only for the platform Super Admin role. */
export function SuperAdminGate({ children }: { children: ReactNode }) {
  const { profile, profileLoading } = useAuth();
  if (!profile && profileLoading) return <main className="flex-1 p-4" aria-busy="true" />;
  if (profile?.platform_role !== "super_admin") {
    return (
      <main className="flex-1 p-4">
        <EmptyState icon={ShieldX} title="Platform Super Admin access required">
          The control plane is granted separately from your workspace role. Ask the platform security owner if you need it.
        </EmptyState>
      </main>
    );
  }
  return <>{children}</>;
}

export function usePlatformDirectory() {
  return useLiveData("platform-directory", (token, signal) => getPlatformDirectory(token, signal), 60_000);
}

export const ACCOUNT_STATUS: Record<PlatformAccountStatus, { tone: "ok" | "warn" | "bad" | "info" | "neutral"; label: string; help: string }> = {
  active: { tone: "ok", label: "Active", help: "Can sign in and has signed in" },
  never_signed_in: { tone: "info", label: "Never signed in", help: "Account ready, not used yet" },
  unconfirmed: { tone: "warn", label: "Email unverified", help: "Has not opened the confirmation link" },
  no_login: { tone: "bad", label: "No login", help: "Profile without a sign-in identity — cannot sign in" },
  suspended: { tone: "bad", label: "Suspended", help: "Sign-in blocked in Supabase" },
  deactivated: { tone: "neutral", label: "Deactivated", help: "Turned off by a company admin" },
};

export const COMPANY_STATE: Record<PlatformCompany["state"], { tone: "ok" | "info" | "neutral" | "warn"; label: string }> = {
  online: { tone: "ok", label: "Online now" },
  active: { tone: "info", label: "Active · 30 days" },
  dormant: { tone: "warn", label: "Dormant" },
  empty: { tone: "neutral", label: "No members" },
};

export function AccountStatusBadge({ status }: { status: PlatformAccountStatus }) {
  const s = ACCOUNT_STATUS[status];
  return <span title={s.help}><Badge tone={s.tone}>{s.label}</Badge></span>;
}

export function OnlineDot({ account }: { account: Pick<PlatformAccount, "online" | "activeSessions"> }) {
  if (account.online) {
    return <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-ok"><span aria-hidden className="h-2 w-2 rounded-full bg-ok" />Online</span>;
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted">
      <span aria-hidden className="h-2 w-2 rounded-full bg-line" />
      {account.activeSessions ? `${account.activeSessions} session${account.activeSessions === 1 ? "" : "s"}` : "Offline"}
    </span>
  );
}

export function matches(query: string, ...fields: (string | null | undefined)[]): boolean {
  const q = query.trim().toLowerCase();
  return !q || fields.some((f) => f?.toLowerCase().includes(q));
}
