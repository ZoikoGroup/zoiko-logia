"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  AlertTriangle, ClipboardCheck, Clock3, KeyRound, ListChecks, Search, ShieldAlert, ShieldCheck, Users,
} from "lucide-react";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import {
  Badge, Breadcrumb, Button, DetailRows, EmptyState, ErrorNote, KpiRow, KpiTile, OpsHero, Panel, PillTabs, ProgressRow,
  inputClass, useMutation, utcDate, utcTime,
} from "@/components/operations/ui";
import { ChecksList } from "@/components/operations/registry";
import { getRolesConsole, getUsersOverview, simulateAccess, type RoleRow, type RolesConsole, type UsersOverview } from "@/lib/api";

type TabKey = "registry" | "matrix" | "effective" | "sod" | "tests";
const TABS: { key: TabKey; label: string }[] = [
  { key: "registry", label: "Role Registry" }, { key: "matrix", label: "Permission Matrix" },
  { key: "effective", label: "Effective Access" }, { key: "sod", label: "Separation of Duties" },
  { key: "tests", label: "Policy Tests" },
];
const roleId = (roles: RoleRow[], name: string) => `ROLE-${String(roles.findIndex((r) => r.name === name) + 1).padStart(3, "0")}`;

export default function RolesPermissionsPage() {
  const { data, error, loading, signedOut, reload } = useLiveData(
    "roles-console", (token, signal) => getRolesConsole(token, signal), 30_000,
  );
  const users = useLiveData("users-overview", (token, signal) => getUsersOverview(token, signal), 30_000);
  const [tab, setTab] = useState<TabKey>("registry");
  const [selected, setSelected] = useState("");
  const roles = useMemo(() => data?.roles ?? [], [data]);
  const role = roles.find((r) => r.name === selected) ?? roles.find((r) => r.sodConflicts.length) ?? roles[0];

  return (
    <main className="flex-1 space-y-4 overflow-y-auto p-4">
      <Breadcrumb section="Administration" page="Roles & Permissions" detail="Enforced access registry" />
      <OpsHero icon={ShieldCheck} title="Roles & Permissions"
        subtitle="Govern who can access what, across tenants, clients, accounting workflows, AI tools, and privileged operations.">
        <p className="text-xs font-bold uppercase tracking-wider text-white">Access governance</p>
        <p className="text-white/75">Least privilege · Separation of duties</p>
        <p className="text-white/75">Explicit denial · Independent approval</p>
      </OpsHero>
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {data && (
        <>
          <p className="flex flex-wrap justify-between gap-2 text-xs text-muted">
            <span><Badge tone="ok">● LIVE · ENFORCED REGISTRY</Badge> The backend checks these permissions on every request.</span>
            <span>Evaluated {utcDate(data.generatedAt)}</span>
          </p>
          <Kpis data={data} />
          <HoldBanner data={data} onInspect={() => setTab("sod")} />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <PillTabs label="Access governance views" tabs={TABS} active={tab} onChange={setTab} />
            <div className="flex gap-2">
              <Button onClick={() => setTab("effective")}>Simulate access</Button>
              <Link href="/users-teams" className="inline-flex min-h-10 items-center rounded-lg border border-accent bg-accent px-3 text-sm font-semibold text-white hover:brightness-95">Assign roles</Link>
            </div>
          </div>
          {tab === "registry" && (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
              <Registry roles={roles} selected={role?.name} onSelect={setSelected} />
              {role && <Inspector role={role} data={data} users={users.data} onTab={setTab} />}
            </div>
          )}
          {tab === "matrix" && <Matrix data={data} />}
          {tab === "effective" && <Simulator data={data} />}
          {tab === "sod" && <SodPanel data={data} />}
          {tab === "tests" && <Panel title="Authorization policy tests" meta={`${data.summary.testsPassed}/${data.summary.testsTotal} passing · run on every view`}>
            <ChecksList checks={data.policyTests.map((t) => ({ label: t.label, status: t.passed ? "pass" : "fail", note: t.detail }))} />
          </Panel>}
          <div className="grid gap-4 xl:grid-cols-3">
            <Matrix data={data} compact />
            <SodPanel data={data} compact />
            <EvidencePanel data={data} />
          </div>
        </>
      )}
    </main>
  );
}

function Kpis({ data }: { data: RolesConsole }) {
  const s = data.summary;
  return (
    <KpiRow>
      <KpiTile icon={ShieldCheck} value={s.roles} label="Governed roles" hint={`${s.privilegedRoles} privileged · ${s.roles - s.privilegedRoles} standard`} />
      <KpiTile icon={Users} tone="ok" value={s.identities} label="Unique identities" hint={`${s.people} people · ${s.serviceAccounts} service accounts`} />
      <KpiTile icon={ShieldAlert} tone={s.sodConflicts ? "bad" : "ok"} value={s.sodConflicts} label="SoD conflicts"
        hint={s.peopleWithConflicts ? `${s.peopleWithConflicts} people hold a conflicted role` : "Roles with conflicting permissions"} />
      <KpiTile icon={Clock3} tone={s.reviewsDue ? "warn" : "ok"} value={s.reviewsDue} label="Access reviews due" hint={`${s.reviewsCompleted} completed to date`} />
      <KpiTile icon={KeyRound} tone={s.activeBreakGlass ? "warn" : "ok"} value={s.activeBreakGlass} label="Active break-glass" hint="No standing tenant-data access" />
      <KpiTile icon={ListChecks} tone={s.testsPassed === s.testsTotal ? "ok" : "warn"} value={`${s.testsPassed} / ${s.testsTotal}`}
        label="Policy tests passing" hint={s.testsPassed === s.testsTotal ? "All checks pass" : `${s.testsTotal - s.testsPassed} check(s) failing`} />
    </KpiRow>
  );
}

function HoldBanner({ data, onInspect }: { data: RolesConsole; onInspect: () => void }) {
  const failing = data.policyTests.filter((t) => !t.passed);
  if (!failing.length) return null;
  return (
    <section className="flex flex-col gap-3 rounded-xl border border-accent/40 border-l-4 border-l-accent bg-accent/5 p-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-start gap-3">
        <AlertTriangle size={20} className="mt-0.5 shrink-0 text-accent-ink" />
        <div>
          <p className="font-bold text-ink">Access governance hold: {failing.length} policy check{failing.length === 1 ? "" : "s"} failing.</p>
          <p className="text-sm text-muted">{failing.map((t) => `${t.label} (${t.detail})`).join(" · ")}</p>
        </div>
      </div>
      <Button onClick={onInspect}>Inspect blockers →</Button>
    </section>
  );
}

function Registry({ roles, selected, onSelect }: { roles: RoleRow[]; selected?: string; onSelect: (name: string) => void }) {
  const [query, setQuery] = useState("");
  const [tier, setTier] = useState("");
  const [sod, setSod] = useState("");
  const rows = roles.filter((r) => (!tier || (tier === "privileged") === r.privileged)
    && (!sod || (sod === "conflict") === r.sodConflicts.length > 0)
    && (!query || `${r.name} ${r.permissions.join(" ")} ${r.purpose}`.toLowerCase().includes(query.toLowerCase())));
  return (
    <Panel title="Role Registry" meta={`${rows.length} displayed / ${roles.length} configured`}>
      <div className="mb-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_auto]">
        <label className="relative">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input className={`${inputClass} pl-9`} placeholder="Search roles, permission scopes or purpose…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <Button onClick={() => { setQuery(""); setTier(""); setSod(""); }}>Clear filters</Button>
      </div>
      <div className="mb-3 grid gap-2 sm:grid-cols-2">
        <select aria-label="Privilege" className={inputClass} value={tier} onChange={(e) => setTier(e.target.value)}>
          <option value="">All privilege tiers</option><option value="privileged">Privileged</option><option value="standard">Standard</option>
        </select>
        <select aria-label="Separation of duties" className={inputClass} value={sod} onChange={(e) => setSod(e.target.value)}>
          <option value="">All SoD states</option><option value="conflict">Conflict</option><option value="clear">Clear</option>
        </select>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[700px] text-left text-sm">
          <thead className="bg-soft text-xs text-muted">
            <tr>{["Role & ID", "Scope", "Users", "Privilege boundary", "SoD", "State", "View"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name} className={`border-b border-line ${selected === r.name ? "bg-info/5" : ""}`}>
                <td className="px-3 py-2.5"><span className="block font-semibold text-ink">{r.name}</span><span className="text-[11px] text-muted">{roleId(roles, r.name)}</span></td>
                <td className="px-3 py-2.5 text-ink">{r.scope}</td>
                <td className="px-3 py-2.5 text-ink">{r.people}{r.serviceAccounts ? <span className="text-xs text-muted"> + {r.serviceAccounts} svc</span> : null}</td>
                <td className="px-3 py-2.5 text-ink">{r.boundary}</td>
                <td className="px-3 py-2.5"><Badge tone={r.sodConflicts.length ? "bad" : "ok"}>{r.sodConflicts.length ? "Conflict" : "Clear"}</Badge></td>
                <td className="px-3 py-2.5"><Badge tone="ok">Enforced</Badge></td>
                <td className="px-3 py-2.5"><button onClick={() => onSelect(r.name)} className="font-semibold text-info hover:underline">Inspect →</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && <EmptyState title="No roles match these filters" />}
      </div>
      <p className="mt-3 text-xs text-muted">Roles are defined in the backend registry and change only through a reviewed code change.</p>
    </Panel>
  );
}

type InspectorTab = "overview" | "permissions" | "holders" | "sod";

function Inspector({ role, data, users, onTab }: { role: RoleRow; data: RolesConsole; users: UsersOverview | null; onTab: (t: TabKey) => void }) {
  const [tab, setTab] = useState<InspectorTab>("overview");
  const holders = (users?.members ?? []).filter((m) => m.role === role.name && m.isActive);
  const denied = data.permissions.filter((p) => !role.permissions.includes(p.key));
  return (
    <Panel title="Role inspector" meta={roleId(data.roles, role.name)} action={<Badge tone={role.sodConflicts.length ? "bad" : "ok"}>{role.sodConflicts.length ? "SoD conflict" : "Clear"}</Badge>}>
      <div className="mb-3 flex items-center gap-3">
        <span className="grid h-11 w-11 place-items-center rounded-lg bg-hero text-accent"><ShieldCheck size={20} /></span>
        <div><p className="text-lg font-extrabold text-ink">{role.name}</p><p className="text-xs text-muted">{role.purpose}</p></div>
      </div>
      <PillTabs label="Role detail" active={tab} onChange={setTab} tabs={[
        { key: "overview", label: "Overview" }, { key: "permissions", label: "Permissions", count: role.permissions.length },
        { key: "holders", label: "Holders", count: role.people }, { key: "sod", label: "SoD & Reviews" }]} />
      <div className="mt-4 space-y-4">
        {tab === "overview" && (
          <>
            <DetailRows rows={[
              ["Defined in", "Backend permission registry"], ["Boundary", role.boundary],
              ["Assigned", `${role.people} people · ${role.serviceAccounts} service accounts`],
              ["Service accounts", role.assignableToServiceAccounts ? "May hold this role" : "Never (needs a person)"],
              ["Step-up (MFA)", role.stepUp.length ? `${role.stepUp.length} privileged permission(s)` : "None"],
              ["Recertification", `Every ${role.reviewInterval} days`],
              ["SoD evaluation", role.sodConflicts.length ? `${role.sodConflicts.length} conflict(s)` : "Clear"],
            ]} />
            <div>
              <h4 className="mb-2 font-bold text-ink">Effective access snapshot</h4>
              <ul className="space-y-2">
                {(denied.length ? denied.slice(0, 3) : data.permissions.slice(0, 3)).map((p) => {
                  const allowed = role.permissions.includes(p.key);
                  return (
                    <li key={p.key} className="flex items-center justify-between rounded-lg border border-line p-2.5 text-sm">
                      <span><span className="block font-semibold text-ink">{p.label}</span><span className="text-xs text-muted">{p.key}</span></span>
                      <Badge tone={allowed ? "ok" : "bad"}>{allowed ? "Allowed" : "Blocked"}</Badge>
                    </li>
                  );
                })}
              </ul>
            </div>
            <p className="rounded-lg border border-accent/30 bg-accent/5 p-3 text-xs text-ink">
              <b>Enforcement precedence:</b> explicit deny → approved break-glass grant (time-boxed) → role permission. Hiding a menu item is not authorization; the backend decides.
            </p>
          </>
        )}
        {tab === "permissions" && (
          <ul className="space-y-1.5 text-sm">
            {data.permissions.map((p) => {
              const allowed = role.permissions.includes(p.key);
              return <li key={p.key} className="flex justify-between gap-2"><span className="text-ink">{p.label}{p.stepUp && <span className="ml-1 text-[10px] text-muted">MFA</span>}</span>
                <span className={`text-xs font-bold ${allowed ? "text-ok" : "text-bad"}`}>{allowed ? "✓ Allow" : "✕ Deny"}</span></li>;
            })}
          </ul>
        )}
        {tab === "holders" && (holders.length ? (
          <ul className="divide-y divide-line text-sm">{holders.map((h) => (
            <li key={h.id} className="flex justify-between py-2"><span className="text-ink">{h.name}</span>
              <span className={`text-xs ${h.reviewOverdue ? "font-bold text-accent-ink" : "text-muted"}`}>{h.reviewOverdue ? "Review due" : "Certified"}</span></li>))}
          </ul>) : <p className="text-sm text-muted">{users ? "Nobody holds this role." : "Loading people…"}</p>)}
        {tab === "sod" && (role.sodConflicts.length ? (
          <ul className="space-y-2 text-sm">{role.sodConflicts.map((c) => (
            <li key={c.permissions.join()} className="rounded-lg border border-bad/30 bg-bad/5 p-2.5"><b className="text-bad">{c.permissions.join(" + ")}</b><br /><span className="text-ink">{c.reason}</span></li>))}
          </ul>) : <p className="text-sm text-muted">No separation-of-duties conflict in this role.</p>)}
        <div className="grid grid-cols-2 gap-2">
          <Button onClick={() => onTab("effective")}>Run policy simulation</Button>
          <Link href="/users-teams" className="inline-flex min-h-10 items-center justify-center rounded-lg border border-line bg-panel text-sm font-semibold text-info hover:bg-soft">View review queue</Link>
        </div>
      </div>
    </Panel>
  );
}

function Matrix({ data, compact = false }: { data: RolesConsole; compact?: boolean }) {
  const columns = compact ? data.roles.filter((r) => ["SME Reviewer", "Risk Admin", "System Auditor", "Admin"].includes(r.name)) : data.roles;
  const rows = compact ? data.permissions.filter((p) => p.stepUp).slice(0, 5) : data.permissions;
  return (
    <Panel title="Effective Permission Matrix" meta={compact ? "Privileged permissions · selected roles" : "Every permission × every role"}>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="bg-soft text-muted"><tr><th className="px-2 py-2">Protected action</th>{columns.map((r) => <th key={r.name} className="px-2 py-2 text-center">{r.name}</th>)}</tr></thead>
          <tbody>{rows.map((p) => (
            <tr key={p.key} className="border-b border-line">
              <td className="px-2 py-1.5 text-ink">{p.label}</td>
              {columns.map((r) => { const ok = r.permissions.includes(p.key); return (
                <td key={r.name} className={`px-2 py-1.5 text-center font-bold ${ok ? "text-ok" : "text-bad"}`}>{ok ? "✓ Allow" : "✕ Deny"}</td>); })}
            </tr>))}</tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-muted">A denied permission can only be added for a limited time through an approved break-glass grant.</p>
    </Panel>
  );
}

function SodPanel({ data, compact = false }: { data: RolesConsole; compact?: boolean }) {
  const s = data.summary;
  return (
    <Panel title="Separation of Duties & Recertification">
      <ul className="space-y-3 text-sm">
        {data.sodRules.map((rule) => (
          <li key={rule.permissions.join()} className="flex items-start gap-2">
            <Badge tone={rule.roles.length ? "bad" : "ok"}>{rule.roles.length ? "BLOCK" : "CLEAR"}</Badge>
            <span><b className="text-ink">{rule.permissions.join(" + ")}</b><br />
              <span className="text-xs text-muted">{rule.reason}{rule.roles.length ? ` · held by ${rule.roles.join(", ")}` : ""}</span></span>
          </li>
        ))}
      </ul>
      <div className="mt-4 space-y-3">
        <ProgressRow label="Completed reviews" value={s.reviewsCompleted} total={Math.max(1, s.reviewsCompleted + s.reviewsDue)} tone="ok" right={s.reviewsCompleted} />
        <ProgressRow label="Reviews due" value={s.reviewsDue} total={Math.max(1, s.people)} tone="warn" right={s.reviewsDue} />
      </div>
      {!compact && <p className="mt-3 rounded-lg border border-accent/30 bg-accent/5 p-3 text-xs text-ink">A role holding both sides of a pair lets one person act and also control the check on that action. Resolve by assigning narrower roles; the registry change needs a reviewed code change.</p>}
    </Panel>
  );
}

function EvidencePanel({ data }: { data: RolesConsole }) {
  return (
    <Panel title="Access Decisions & Audit Evidence">
      {data.events.length ? (
        <ul className="space-y-2.5 text-sm">
          {data.events.slice(0, 6).map((e) => (
            <li key={e.id} className="flex gap-2">
              <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-accent" />
              <span><b className="text-ink">{utcTime(e.at)}</b> <span className="text-ink">{e.event.replace(/_/g, " ").replace(/\./g, " ")}</span>
                <span className="block text-xs text-muted">{e.actor}{e.detail.required ? ` · needed ${String(e.detail.required)}` : ""}{e.detail.new_role ? ` · ${String(e.detail.previous_role)} → ${String(e.detail.new_role)}` : ""}</span></span>
            </li>
          ))}
        </ul>
      ) : <p className="text-sm text-muted">No access decisions recorded yet.</p>}
      <p className="mt-3 rounded-lg border border-line bg-soft p-2.5 text-xs text-ink"><b>Audit lineage:</b> request → tenant scope → role permission → decision → hash-chained audit event.</p>
    </Panel>
  );
}

function Simulator({ data }: { data: RolesConsole }) {
  const [role, setRole] = useState(data.roles[0]?.name ?? "");
  const [permission, setPermission] = useState(data.permissions[0]?.key ?? "");
  const [mfa, setMfa] = useState(false);
  const [result, setResult] = useState<{ decision: string; reason: string } | null>(null);
  const { busy, error, run } = useMutation();
  const tone = result?.decision === "allow" ? "ok" : result?.decision === "step_up" ? "warn" : "bad";
  return (
    <Panel title="Effective access simulation" meta="Asks the backend's own rules; changes nothing">
      <div className="grid gap-2 md:grid-cols-[1fr_1fr_auto_auto]">
        <select aria-label="Role" className={inputClass} value={role} onChange={(e) => setRole(e.target.value)}>{data.roles.map((r) => <option key={r.name}>{r.name}</option>)}</select>
        <select aria-label="Permission" className={inputClass} value={permission} onChange={(e) => setPermission(e.target.value)}>{data.permissions.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}</select>
        <label className="flex items-center gap-2 text-sm text-ink"><input type="checkbox" checked={mfa} onChange={(e) => setMfa(e.target.checked)} /> MFA session</label>
        <Button variant="primary" busy={busy === "sim"} onClick={() => run("sim", async (t) => setResult(await simulateAccess(t, { role, permission, session_mfa: mfa })))}>Simulate</Button>
      </div>
      <ErrorNote message={error} />
      {result && (
        <div className="mt-4 flex items-center gap-3 rounded-lg border border-line p-3">
          <Badge tone={tone}>{result.decision === "step_up" ? "MFA REQUIRED" : result.decision.toUpperCase()}</Badge>
          <span className="text-sm text-ink">{result.reason}</span>
        </div>
      )}
      <p className="mt-3 flex items-center gap-1.5 text-xs text-muted"><ClipboardCheck size={13} /> Uses this tenant&apos;s effective MFA policy.</p>
    </Panel>
  );
}
