"use client";

import { useState } from "react";
import { Activity, LogIn, MailWarning, Search, ShieldCheck, UserX, Users } from "lucide-react";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import {
  Avatar, Badge, Breadcrumb, EmptyState, KpiRow, KpiTile, OpsHero, Panel, PillTabs, inputClass, timeAgo, utcDate,
} from "@/components/operations/ui";
import {
  ACCOUNT_STATUS, AccountStatusBadge, OnlineDot, SuperAdminGate, matches, usePlatformDirectory,
} from "@/components/platform/directory";
import type { PlatformAccountStatus, PlatformDirectory } from "@/lib/api";

type StatusTab = "all" | "online" | PlatformAccountStatus;
const PAGE = 50;

/** Every account on the platform, across every company and role, with its
 * sign-in status. */
export default function AccountsPage() {
  return <SuperAdminGate><Accounts /></SuperAdminGate>;
}

function Accounts() {
  const { data, error, loading, signedOut, reload } = usePlatformDirectory();
  return (
    <main className="flex-1 space-y-4 overflow-y-auto p-4">
      <Breadcrumb section="Platform control plane" page="Accounts" />
      <OpsHero icon={Users} eyebrow="Platform directory" title="Accounts"
        subtitle="Every person on the platform: company, role, account status and sign-in activity.">
        {data && <p className="font-bold text-white">{data.summary.online} signed in now · {data.summary.signedIn24h} in the last 24 h</p>}
        <p>Global platform · all tenants and roles</p>
        {data && <p className="text-xs text-white/70">Measured {utcDate(data.generatedAt)}</p>}
      </OpsHero>
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {data && <Body data={data} />}
    </main>
  );
}

function Body({ data }: { data: PlatformDirectory }) {
  const s = data.summary;
  const now = new Date(data.generatedAt).getTime();
  const [tab, setTab] = useState<StatusTab>("all");
  const [role, setRole] = useState("any");
  const [company, setCompany] = useState("any");
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(PAGE);

  const count = (st: PlatformAccountStatus) => s.statuses[st] ?? 0;
  const rows = data.accounts.filter((a) =>
    (tab === "all" || (tab === "online" ? a.online : a.status === tab))
    && (role === "any" || a.role === role) && (company === "any" || a.tenantId === company)
    && matches(query, a.name, a.email, a.tenant));
  const unverified = count("unconfirmed") + count("never_signed_in");
  const blocked = count("no_login") + count("suspended") + count("deactivated");

  return (
    <>
      <KpiRow>
        <KpiTile icon={Users} value={s.accounts} label="Accounts" hint={`${Object.keys(s.roles).length} roles across ${s.companies + s.personalWorkspaces} workspaces`} />
        <KpiTile icon={Activity} value={s.online} label="Signed in now" tone={s.online ? "ok" : "neutral"} hint="Session active in the last hour" />
        <KpiTile icon={LogIn} value={s.signedIn24h} label="Signed in · 24 h" hint={`${s.signedIn7d} in the last 7 days`} />
        <KpiTile icon={ShieldCheck} value={count("active")} label="Active accounts" tone="ok" hint={`${s.withMfa} with two-step verification`} />
        <KpiTile icon={MailWarning} value={unverified} label="Not yet in use" tone={unverified ? "warn" : "ok"}
          hint={`${count("unconfirmed")} unverified · ${count("never_signed_in")} never signed in`} />
        <KpiTile icon={UserX} value={blocked} label="Cannot sign in" tone={blocked ? "bad" : "ok"}
          hint={`${count("no_login")} no login · ${count("deactivated")} deactivated`} />
      </KpiRow>

      <Panel title="All accounts" meta={`${rows.length} shown`}>
        <div className="mb-3 space-y-2">
          <PillTabs label="Status" active={tab} onChange={(t) => { setTab(t); setLimit(PAGE); }} tabs={[
            { key: "all", label: "All", count: s.accounts },
            { key: "online", label: "Online", count: s.online },
            ...(Object.keys(ACCOUNT_STATUS) as PlatformAccountStatus[])
              .filter((st) => count(st) > 0)
              .map((st) => ({ key: st, label: ACCOUNT_STATUS[st].label, count: count(st) })),
          ]} />
          <div className="grid gap-2 sm:grid-cols-3">
            <label className="relative block">
              <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
              <input value={query} onChange={(e) => { setQuery(e.target.value); setLimit(PAGE); }} placeholder="Search name, email or company"
                aria-label="Search accounts" className={`${inputClass} pl-8`} />
            </label>
            <select aria-label="Role" value={role} onChange={(e) => setRole(e.target.value)} className={inputClass}>
              <option value="any">All roles</option>
              {Object.entries(s.roles).sort().map(([r, n]) => <option key={r} value={r}>{r} ({n})</option>)}
            </select>
            <select aria-label="Company" value={company} onChange={(e) => setCompany(e.target.value)} className={inputClass}>
              <option value="any">All companies</option>
              {[...data.companies].sort((a, b) => a.name.localeCompare(b.name)).map((c) => (
                <option key={c.id} value={c.id}>{c.name}{c.type === "personal" ? " (personal)" : ""}</option>
              ))}
            </select>
          </div>
        </div>

        {rows.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[880px] text-sm">
              <thead><tr className="border-b border-line text-left text-[11px] uppercase tracking-wide text-muted">
                <th className="py-2 pr-3">Person</th><th className="py-2 pr-3">Company</th><th className="py-2 pr-3">Role</th>
                <th className="py-2 pr-3">Status</th><th className="py-2 pr-3">Security</th><th className="py-2 pr-3">Last sign-in</th>
                <th className="py-2">Now</th>
              </tr></thead>
              <tbody>{rows.slice(0, limit).map((a) => (
                <tr key={a.id} className="border-b border-line last:border-0">
                  <td className="py-2.5 pr-3">
                    <div className="flex items-center gap-2.5">
                      <Avatar name={a.name} />
                      <div className="min-w-0"><div className="font-semibold text-ink">{a.name}</div><div className="truncate text-xs text-muted">{a.email}</div></div>
                    </div>
                  </td>
                  <td className="py-2.5 pr-3 text-ink">{a.tenant || "—"}</td>
                  <td className="py-2.5 pr-3">
                    <Badge tone={a.role === "Admin" ? "info" : "neutral"}>{a.role}</Badge>
                    {a.platformRole === "super_admin" && <div className="mt-1"><Badge tone="warn">Super Admin</Badge></div>}
                  </td>
                  <td className="py-2.5 pr-3"><AccountStatusBadge status={a.status} /></td>
                  <td className="py-2.5 pr-3 text-xs text-muted">
                    <div>{a.emailConfirmed === null ? "Email —" : a.emailConfirmed ? "Email verified" : "Email unverified"}</div>
                    <div>{a.mfa === null ? "2-step —" : a.mfa ? "2-step on" : "2-step off"}{a.providers.length ? ` · ${a.providers.join(", ")}` : ""}</div>
                  </td>
                  <td className="py-2.5 pr-3">
                    <div className="text-ink">{a.lastSignInAt ? timeAgo(a.lastSignInAt, now) : "Never"}</div>
                    <div className="text-xs text-muted">Joined {utcDate(a.createdAt).split(" · ")[0]}</div>
                  </td>
                  <td className="py-2.5"><OnlineDot account={a} /></td>
                </tr>))}</tbody>
            </table>
            {rows.length > limit && (
              <div className="mt-3 text-center">
                <button type="button" onClick={() => setLimit((n) => n + PAGE)} className="text-sm font-semibold text-info hover:underline">
                  Show {Math.min(PAGE, rows.length - limit)} more of {rows.length - limit}
                </button>
              </div>
            )}
          </div>
        ) : <EmptyState icon={Users} title="No account matches these filters" />}
      </Panel>
    </>
  );
}
