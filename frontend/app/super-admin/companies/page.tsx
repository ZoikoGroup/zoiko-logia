"use client";

import { useMemo, useState } from "react";
import { Activity, Building2, CircleUser, Clock, LogIn, Search, TriangleAlert, Users } from "lucide-react";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import {
  Avatar, Badge, Breadcrumb, DetailRows, EmptyState, KpiRow, KpiTile, OpsHero, Panel, PillTabs, inputClass, timeAgo, utcDate,
} from "@/components/operations/ui";
import {
  AccountStatusBadge, COMPANY_STATE, OnlineDot, SuperAdminGate, matches, usePlatformDirectory,
} from "@/components/platform/directory";
import type { PlatformAccount, PlatformCompany, PlatformDirectory } from "@/lib/api";

type TypeTab = "all" | "company" | "personal";
type StateFilter = "any" | PlatformCompany["state"];

/** Every company (and personal workspace) on the platform: who runs it, who
 * is signed in, and the status of each of its accounts. */
export default function CompaniesPage() {
  return <SuperAdminGate><Companies /></SuperAdminGate>;
}

function Companies() {
  const { data, error, loading, signedOut, reload } = usePlatformDirectory();
  return (
    <main className="flex-1 space-y-4 overflow-y-auto p-4">
      <Breadcrumb section="Platform control plane" page="Companies" />
      <OpsHero icon={Building2} eyebrow="Platform directory" title="Companies"
        subtitle="Every company and personal workspace, its admins, members and sign-in activity.">
        {data && <p className="font-bold text-white">{data.summary.companiesOnline} compan{data.summary.companiesOnline === 1 ? "y" : "ies"} online now</p>}
        <p>Global platform · all tenants</p>
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
  const [tab, setTab] = useState<TypeTab>("company");
  const [state, setState] = useState<StateFilter>("any");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const membersByCompany = useMemo(() => {
    const map = new Map<string, PlatformAccount[]>();
    for (const a of data.accounts) map.set(a.tenantId, [...(map.get(a.tenantId) ?? []), a]);
    return map;
  }, [data.accounts]);

  const rows = data.companies.filter((c) =>
    (tab === "all" || c.type === tab) && (state === "any" || c.state === state)
    && matches(query, c.name, ...c.admins.map((a) => a.email), ...(membersByCompany.get(c.id) ?? []).map((m) => m.email)));
  const selected = data.companies.find((c) => c.id === selectedId) ?? null;
  const issues = data.companies.filter((c) => c.type === "company" && c.issues > 0).length;

  return (
    <>
      <KpiRow>
        <KpiTile icon={Building2} value={s.companies} label="Companies" hint={`${s.personalWorkspaces} personal workspaces`} />
        <KpiTile icon={Activity} value={s.companiesOnline} label="Online now" tone={s.companiesOnline ? "ok" : "neutral"}
          hint={`${s.online} account${s.online === 1 ? "" : "s"} signed in`} />
        <KpiTile icon={LogIn} value={s.companiesSignedIn24h} label="Signed in · 24 h" hint={`${s.signedIn24h} accounts`} />
        <KpiTile icon={Clock} value={s.companiesActive30d} label="Active · 30 days" hint={`${s.companies - s.companiesActive30d} dormant or empty`} />
        <KpiTile icon={Users} value={s.accounts} label="Accounts" hint={`${s.roles.Admin ?? 0} admins · ${s.roles.Learner ?? 0} learners`} />
        <KpiTile icon={TriangleAlert} value={issues} label="Companies with account issues" tone={issues ? "warn" : "ok"}
          hint="Unverified email, no login or suspended" />
      </KpiRow>

      {!data.signInDataAvailable && (
        <p className="rounded-lg border border-line bg-soft px-3 py-2 text-xs text-muted">
          Sign-in data is unavailable on this database, so sign-in times and online status show as unknown.
        </p>
      )}

      <div className={`grid gap-4 ${selected ? "xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]" : ""}`}>
        <Panel title="All companies" meta={`${rows.length} shown`}>
          <div className="mb-3 flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
            <PillTabs label="Type" active={tab} onChange={setTab} tabs={[
              { key: "company", label: "Companies", count: s.companies },
              { key: "personal", label: "Personal", count: s.personalWorkspaces },
              { key: "all", label: "All", count: data.companies.length },
            ]} />
            <div className="flex gap-2">
              <select aria-label="Activity" value={state} onChange={(e) => setState(e.target.value as StateFilter)} className={`${inputClass} w-40`}>
                <option value="any">Any activity</option>
                {Object.entries(COMPANY_STATE).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </select>
              <label className="relative block w-full lg:w-64">
                <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
                <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search company or email"
                  aria-label="Search companies" className={`${inputClass} pl-8`} />
              </label>
            </div>
          </div>
          {rows.length ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-sm">
                <thead><tr className="border-b border-line text-left text-[11px] uppercase tracking-wide text-muted">
                  <th className="py-2 pr-3">Company</th><th className="py-2 pr-3">Status</th><th className="py-2 pr-3">Admin</th>
                  <th className="py-2 pr-3">Members</th><th className="py-2 pr-3">Online</th><th className="py-2">Last sign-in</th>
                </tr></thead>
                <tbody>{rows.map((c) => (
                  <tr key={c.id} onClick={() => setSelectedId(c.id === selectedId ? null : c.id)}
                    className={`cursor-pointer border-b border-line last:border-0 hover:bg-soft ${c.id === selectedId ? "bg-accent/5" : ""}`}>
                    <td className="py-2.5 pr-3">
                      <button type="button" className="text-left font-semibold text-ink hover:underline" aria-expanded={c.id === selectedId}>{c.name}</button>
                      <div className="text-xs text-muted">{c.type === "personal" ? "Personal workspace" : "Company"}{c.billingPlan ? " · billing plan" : ""}</div>
                    </td>
                    <td className="py-2.5 pr-3"><Badge tone={COMPANY_STATE[c.state].tone}>{COMPANY_STATE[c.state].label}</Badge>
                      {c.issues > 0 && <div className="mt-1 text-xs font-semibold text-accent-ink">{c.issues} account issue{c.issues === 1 ? "" : "s"}</div>}</td>
                    <td className="py-2.5 pr-3">{c.admins[0]
                      ? <><div className="text-ink">{c.admins[0].name}</div><div className="text-xs text-muted">{c.admins[0].email}{c.admins.length > 1 ? ` +${c.admins.length - 1}` : ""}</div></>
                      : <span className="text-muted">—</span>}</td>
                    <td className="py-2.5 pr-3 text-ink">{c.activeMembers} / {c.members}</td>
                    <td className="py-2.5 pr-3">{c.online ? <span className="font-semibold text-ok">{c.online}</span> : <span className="text-muted">0</span>}</td>
                    <td className="py-2.5 text-ink">{timeAgo(c.lastSignInAt, now)}</td>
                  </tr>))}</tbody>
              </table>
            </div>
          ) : <EmptyState icon={Building2} title="No company matches these filters" />}
        </Panel>

        {selected && <CompanyDetail company={selected} members={membersByCompany.get(selected.id) ?? []} now={now} onClose={() => setSelectedId(null)} />}
      </div>
    </>
  );
}

function CompanyDetail({ company, members, now, onClose }: {
  company: PlatformCompany; members: PlatformAccount[]; now: number; onClose: () => void;
}) {
  return (
    <Panel title={company.name} meta={company.type === "personal" ? "Personal workspace" : "Company"}
      action={<button type="button" onClick={onClose} className="text-xs font-semibold text-info hover:underline">Close</button>}
      className="xl:sticky xl:top-20 xl:self-start">
      <DetailRows rows={[
        ["Status", <Badge key="s" tone={COMPANY_STATE[company.state].tone}>{COMPANY_STATE[company.state].label}</Badge>],
        ["Created", utcDate(company.createdAt)],
        ["Members", `${company.activeMembers} active of ${company.members}`],
        ["Roles", Object.entries(company.roles).map(([r, n]) => `${n} ${r}`).join(" · ") || "—"],
        ["Signed in", `${company.online} now · ${company.signedIn24h} in 24 h · ${company.signedIn7d} in 7 days`],
        ["Last sign-in", company.lastSignInAt ? `${timeAgo(company.lastSignInAt, now)} · ${utcDate(company.lastSignInAt)}` : "Never"],
        ["Last activity", timeAgo(company.lastActivityAt, now)],
        ["Billing plan", company.billingPlan ? "Approved plan" : "None"],
      ]} />
      <h3 className="mb-2 mt-4 text-sm font-bold text-ink">Accounts ({members.length})</h3>
      {members.length ? (
        <ul className="divide-y divide-line">
          {members.map((m) => (
            <li key={m.id} className="flex items-start gap-3 py-2.5">
              <Avatar name={m.name} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-ink">{m.name}</span>
                  <Badge tone={m.role === "Admin" ? "info" : "neutral"}>{m.role}</Badge>
                  {m.platformRole === "super_admin" && <Badge tone="warn">Super Admin</Badge>}
                </div>
                <div className="truncate text-xs text-muted">{m.email}</div>
                <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                  <AccountStatusBadge status={m.status} />
                  <OnlineDot account={m} />
                  <span><CircleUser size={11} className="mr-1 inline" />Last sign-in {timeAgo(m.lastSignInAt, now)}</span>
                </div>
              </div>
            </li>
          ))}
        </ul>
      ) : <p className="text-sm text-muted">No accounts in this workspace.</p>}
    </Panel>
  );
}
