"use client";

import { useMemo, useState } from "react";
import { Bot, Copy, Diamond, KeyRound, ShieldAlert, ShieldX, UserCheck, Search, CalendarClock } from "lucide-react";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import {
  Badge, Breadcrumb, Button, DetailRows, EmptyState, ErrorNote, KpiRow, KpiTile, OpsHero, Panel, PillTabs, ProgressRow,
  humanize, inputClass, timeAgo, useMutation, utcDate,
} from "@/components/operations/ui";
import { ChecksList } from "@/components/operations/registry";
import { BACKEND_ROLES } from "@/lib/roles";
import {
  createServiceAccount, getAdminActivity, getAssignees, getServiceAccountsOverview, issueServiceAccountKey,
  revokeServiceAccountKey, transferServiceAccount, type ActivityEvent, type Assignee, type ServiceAccountRow,
  type ServiceAccountsOverview,
} from "@/lib/api";

const SERVICE_ROLES = BACKEND_ROLES.filter((r) => r !== "Admin");
const KEY_LIFETIMES = [30, 90, 180, 365];
const STATE: Record<ServiceAccountRow["state"], { label: string; tone: "ok" | "warn" | "bad" | "neutral" }> = {
  active: { label: "Active", tone: "ok" }, restricted: { label: "Renewal due", tone: "warn" },
  quarantined: { label: "Quarantined", tone: "bad" }, dormant: { label: "Dormant", tone: "neutral" },
  no_credential: { label: "No credential", tone: "neutral" }, disabled: { label: "Disabled", tone: "neutral" },
};
const RISK_TONE = { critical: "bad", high: "bad", medium: "warn", low: "ok" } as const;
const saId = (rows: ServiceAccountRow[], id: string) => `SA-${String(rows.findIndex((r) => r.id === id) + 1).padStart(3, "0")}`;
type TabKey = "all" | "credentials" | "permissions" | "attestations" | "usage";

export default function ServiceAccountsPage() {
  const { data, error, loading, signedOut, reload } = useLiveData(
    "service-accounts-overview", (token, signal) => getServiceAccountsOverview(token, signal), 30_000,
  );
  const people = useLiveData("ops-assignees", (token, signal) => getAssignees(token, signal), 20_000);
  const [tab, setTab] = useState<TabKey>("all");
  const [selectedId, setSelectedId] = useState("");
  const [creating, setCreating] = useState(false);
  const [issued, setIssued] = useState<{ accountName: string; key: string } | null>(null);
  const accounts = useMemo(() => data?.accounts ?? [], [data]);
  const selected = accounts.find((a) => a.id === selectedId) ?? accounts.find((a) => a.state === "quarantined") ?? accounts[0];

  return (
    <main className="flex-1 space-y-4 overflow-y-auto p-4">
      <Breadcrumb section="Administration" page="Service Accounts" />
      <OpsHero icon={Bot} eyebrow="Machine identity governance" title="Service Accounts"
        subtitle="Authorize workload identities, manage credentials, and protect tenant boundaries.">
        <p>Least privilege · Non-human identity</p><p>Secrets never displayed</p>
        <p>Rotation, attestation and revocation</p><p>Auditable machine access</p>
      </OpsHero>
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {issued && (
        <section role="status" className="rounded-xl border border-ok/30 bg-ok/5 p-4">
          <p className="font-bold text-ink">New API key for {issued.accountName}: copy it now; it will never be shown again.</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <code className="break-all rounded-lg border border-line bg-panel px-3 py-2 text-sm text-ink">{issued.key}</code>
            <Button onClick={() => navigator.clipboard?.writeText(issued.key)}><Copy size={14} /> Copy</Button>
            <Button onClick={() => setIssued(null)}>I have stored it</Button>
          </div>
        </section>
      )}
      {data && (
        <>
          <Kpis data={data} />
          {creating && <CreateForm people={people.data ?? []} onDone={() => { setCreating(false); reload(); }} />}
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_440px]">
            <Panel title="Service Account Register" meta="Workload identities in this workspace"
              action={<Button variant="primary" onClick={() => setCreating(true)}>+ Register Account</Button>}>
              <PillTabs label="Service account views" active={tab} onChange={setTab} tabs={[
                { key: "all", label: "All Accounts" }, { key: "credentials", label: "Credentials" },
                { key: "permissions", label: "Permissions" }, { key: "attestations", label: "Attestations" },
                { key: "usage", label: "Usage & Anomalies" }]} />
              <div className="mt-3"><Register rows={accounts} tab={tab} selectedId={selected?.id} onSelect={setSelectedId} /></div>
            </Panel>
            {selected ? <Detail key={selected.id} a={selected} all={accounts} people={people.data ?? []} onIssued={setIssued} onChanged={reload} />
              : <Panel title="Service account"><EmptyState icon={Bot} title="No service accounts yet">Register one for each integration that calls the API.</EmptyState></Panel>}
          </div>
          <Bottom data={data} onSelect={setSelectedId} />
        </>
      )}
    </main>
  );
}

function Kpis({ data }: { data: ServiceAccountsOverview }) {
  const s = data.summary;
  return (
    <KpiRow>
      <KpiTile icon={Diamond} value={s.accounts} label="Service Accounts" hint="Inventoried machine identities" />
      <KpiTile icon={KeyRound} tone="ok" value={s.liveKeys} label="Live API Keys" hint="Hashed at rest · shown once" />
      <KpiTile icon={CalendarClock} tone={s.renewals ? "warn" : "ok"} value={s.renewals} label="Credential Renewals" hint="Keys expiring within 7 days" />
      <KpiTile icon={ShieldAlert} tone={s.scopeExceptions ? "warn" : "ok"} value={s.scopeExceptions} label="Scope Exceptions" hint="Can change governed state" />
      <KpiTile icon={UserCheck} tone={s.ownershipReviews ? "bad" : "ok"} value={s.ownershipReviews} label="Ownership Reviews" hint="Owner deactivated" />
      <KpiTile icon={ShieldX} tone={s.quarantined ? "bad" : "ok"} value={s.quarantined} label="Quarantined Identity" hint="Unowned with a live credential" />
    </KpiRow>
  );
}

function Register({ rows, tab, selectedId, onSelect }: { rows: ServiceAccountRow[]; tab: TabKey; selectedId?: string; onSelect: (id: string) => void }) {
  const [query, setQuery] = useState("");
  const [role, setRole] = useState("");
  const [state, setState] = useState("");
  const [risk, setRisk] = useState("");
  const shown = rows.filter((a) => (tab !== "credentials" || a.liveKeys > 0 || a.keys.length > 0)
    && (tab !== "permissions" || a.permissions.length > 0) && (tab !== "attestations" || a.checksPassed < 5)
    && (tab !== "usage" || !a.lastUsedAt || a.state !== "active")
    && (!role || a.role === role) && (!state || a.state === state) && (!risk || a.risk === risk)
    && (!query || `${a.name} ${a.description} ${a.owner} ${saId(rows, a.id)}`.toLowerCase().includes(query.toLowerCase())));
  return (
    <>
      <div className="mb-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_auto]">
        <label className="relative">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input className={`${inputClass} pl-9`} placeholder="Search machine identity, purpose, owner, or account ID…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <Button onClick={() => { setQuery(""); setRole(""); setState(""); setRisk(""); }}>Clear</Button>
      </div>
      <div className="mb-3 grid gap-2 sm:grid-cols-3">
        <select aria-label="Role" className={inputClass} value={role} onChange={(e) => setRole(e.target.value)}><option value="">All roles</option>{SERVICE_ROLES.map((r) => <option key={r}>{r}</option>)}</select>
        <select aria-label="State" className={inputClass} value={state} onChange={(e) => setState(e.target.value)}><option value="">All states</option>{Object.entries(STATE).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select>
        <select aria-label="Risk" className={inputClass} value={risk} onChange={(e) => setRisk(e.target.value)}><option value="">All risks</option>{["critical", "high", "medium", "low"].map((r) => <option key={r} value={r}>{humanize(r)}</option>)}</select>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead className="bg-soft text-xs uppercase text-muted">
            <tr>{["Machine identity / ID", "Purpose / owner", "Role", "Auth method", "State", "Risk"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr>
          </thead>
          <tbody>
            {shown.map((a) => (
              <tr key={a.id} onClick={() => onSelect(a.id)} aria-selected={selectedId === a.id}
                className={`cursor-pointer border-b border-line hover:bg-soft ${selectedId === a.id ? "border-l-4 border-l-info bg-info/5" : ""}`}>
                <td className="px-3 py-2.5"><b className="block text-ink">{a.name}</b><span className="font-mono text-[11px] text-muted">{saId(rows, a.id)}</span></td>
                <td className="px-3 py-2.5"><span className="block text-ink">{a.description || "—"}</span><span className="text-xs text-muted">Owner: {a.owner}{a.ownerActive ? "" : " (deactivated)"}</span></td>
                <td className="px-3 py-2.5 text-ink">{a.role}</td>
                <td className="px-3 py-2.5"><span className="block text-ink">API key (hashed)</span><span className="text-xs text-muted">{a.nextExpiry ? `Expires ${utcDate(a.nextExpiry).split(" · ")[0]}` : "No live key"}</span></td>
                <td className="px-3 py-2.5"><Badge tone={STATE[a.state].tone}>{STATE[a.state].label}</Badge></td>
                <td className="px-3 py-2.5"><Badge tone={RISK_TONE[a.risk]}>{humanize(a.risk)}</Badge></td>
              </tr>
            ))}
          </tbody>
        </table>
        {!shown.length && <EmptyState title={rows.length ? "No accounts match this view" : "No service accounts registered"} />}
      </div>
      <p className="mt-3 text-xs text-muted">{shown.length} of {rows.length} machine identities shown</p>
    </>
  );
}

type DetailTab = "overview" | "access" | "credentials" | "activity";

function Detail({ a, all, people, onIssued, onChanged }: {
  a: ServiceAccountRow; all: ServiceAccountRow[]; people: Assignee[]; onIssued: (v: { accountName: string; key: string }) => void; onChanged: () => void;
}) {
  const [tab, setTab] = useState<DetailTab>("overview");
  const [lifetime, setLifetime] = useState(90);
  const [events, setEvents] = useState<ActivityEvent[] | null>(null);
  const { busy, error, run } = useMutation();
  const done = (ok: boolean) => ok && onChanged();
  const liveKeys = a.keys.filter((k) => !k.revokedAt && k.expiresAt && new Date(k.expiresAt) > new Date());
  return (
    <Panel title={a.name} meta={saId(all, a.id)} action={<Badge tone={STATE[a.state].tone}>{STATE[a.state].label}</Badge>}>
      <p className="-mt-2 mb-3 text-sm text-muted">{a.description || "No purpose recorded"}</p>
      <PillTabs label="Service account detail" active={tab} onChange={(t) => { setTab(t); if (t === "activity" && events === null) run("activity", async (tok) => setEvents(await getAdminActivity(tok, a.id))); }}
        tabs={[{ key: "overview", label: "Overview" }, { key: "access", label: "Effective Access" },
          { key: "credentials", label: "Credentials", count: a.keys.length }, { key: "activity", label: "Activity" }]} />
      <div className="mt-4 space-y-4">
        {(a.state === "quarantined" || a.state === "restricted") && (
          <div className={`rounded-lg border p-3 ${a.state === "quarantined" ? "border-bad/30 bg-bad/5" : "border-accent/40 bg-accent/5"}`}>
            <p className={`text-sm font-bold ${a.state === "quarantined" ? "text-bad" : "text-accent-ink"}`}>{a.state === "quarantined" ? "QUARANTINED MACHINE IDENTITY" : "RESTRICTED MACHINE IDENTITY"}</p>
            <p className="text-sm text-ink">{a.state === "quarantined"
              ? "Its owner is deactivated. Assign an active owner before issuing or rotating credentials."
              : `${a.expiringKeys} key(s) expire within 7 days. Issue a replacement, update the integration, then revoke the old key.`}</p>
          </div>
        )}
        {tab === "overview" && (
          <>
            <DetailRows rows={[
              ["Account ID", saId(all, a.id)], ["Owner", `${a.owner}${a.ownerActive ? "" : " (deactivated)"}`],
              ["Workload purpose", a.description || "—"], ["Role", a.role], ["Authentication", "API key, stored only as a hash"],
              ["Credential expiry", a.nextExpiry ? utcDate(a.nextExpiry) : "No live key"],
              ["Last usage (UTC)", a.lastUsedAt ? `${utcDate(a.lastUsedAt)} (${timeAgo(a.lastUsedAt)})` : "Never"],
              ["Created by", `${a.createdBy} · ${a.createdAt ? utcDate(a.createdAt).split(" · ")[0] : ""}`],
              ["Assessed risk", humanize(a.risk)],
            ]} />
            <ChecksList title={`Required authorization checks · ${a.checksPassed}/${a.checks.length}`} checks={a.checks} />
          </>
        )}
        {tab === "access" && (
          <div className="space-y-2 text-sm">
            <p className="text-ink">Role <b>{a.role}</b> grants {a.permissions.length ? a.permissions.join(", ") : "no governance permissions"}.</p>
            <p className="text-xs text-muted">A service account can never hold Admin, cannot impersonate, and is exempt from MFA step-up only because it is bounded by its owner, expiry and revocation.</p>
          </div>
        )}
        {tab === "credentials" && (a.keys.length ? (
          <ul className="space-y-2 text-sm">{a.keys.map((k) => {
            const live = !k.revokedAt && k.expiresAt && new Date(k.expiresAt) > new Date();
            return (
              <li key={k.id} className="flex items-center justify-between gap-2 rounded-lg border border-line p-2.5">
                <span><code className="text-ink">{k.prefix}…</code><span className="block text-xs text-muted">Created {k.createdAt ? utcDate(k.createdAt).split(" · ")[0] : ""} · expires {k.expiresAt ? utcDate(k.expiresAt).split(" · ")[0] : ""} · {k.lastUsedAt ? `used ${timeAgo(k.lastUsedAt)}` : "never used"}</span></span>
                {live ? <Button variant="danger" busy={busy === k.id} onClick={() => run(k.id, (t) => revokeServiceAccountKey(t, a.id, k.id)).then(done)}>Revoke</Button>
                  : <Badge tone="neutral">{k.revokedAt ? "Revoked" : "Expired"}</Badge>}
              </li>);
          })}</ul>) : <p className="text-sm text-muted">No keys issued.</p>)}
        {tab === "activity" && (events === null ? <p className="text-sm text-muted">Loading…</p> : events.length ? (
          <ul className="space-y-2 text-sm">{events.map((e) => <li key={e.id}><b className="text-ink">{e.event.replace(/[._]/g, " ")}</b> <span className="text-xs text-muted">· {e.actor} · {utcDate(e.at)}</span></li>)}</ul>
        ) : <p className="text-sm text-muted">No recorded events.</p>)}
        <ErrorNote message={error} />
        <div className="space-y-2 border-t border-line pt-3">
          <div className="grid grid-cols-[auto_1fr] gap-2">
            <select aria-label="Key lifetime" className={inputClass} value={lifetime} onChange={(e) => setLifetime(Number(e.target.value))}>
              {KEY_LIFETIMES.map((d) => <option key={d} value={d}>{d} days</option>)}
            </select>
            <Button variant="primary" disabled={!a.ownerActive || !a.isActive} busy={busy === "issue"}
              title={a.ownerActive ? "Shown once" : "Assign an active owner first"}
              onClick={() => run("issue", async (t) => { const r = await issueServiceAccountKey(t, a.id, lifetime); onIssued({ accountName: a.name, key: r.key }); }).then(done)}>
              {liveKeys.length ? "Rotate: issue new key" : "Issue API key"}
            </Button>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <select aria-label="Transfer ownership" className={inputClass} value="" disabled={busy === "owner"}
              onChange={(e) => e.target.value && run("owner", (t) => transferServiceAccount(t, a.id, e.target.value)).then(done)}>
              <option value="">Transfer ownership…</option>{people.filter((p) => p.id !== a.ownerId).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <Button variant="danger" disabled={!liveKeys.length} busy={busy === "revoke-all"}
              onClick={() => window.confirm(`Revoke every live key of ${a.name}?`) && run("revoke-all", async (t) => { for (const k of liveKeys) await revokeServiceAccountKey(t, a.id, k.id); }).then(done)}>Revoke all keys</Button>
          </div>
        </div>
      </div>
    </Panel>
  );
}

function Bottom({ data, onSelect }: { data: ServiceAccountsOverview; onSelect: (id: string) => void }) {
  const total = Math.max(1, data.summary.accounts);
  const st = data.summary.states;
  const keys = data.accounts.flatMap((a) => a.keys);
  const revoked = keys.filter((k) => k.revokedAt).length;
  const priority = data.accounts.filter((a) => a.state !== "active" || a.checksPassed < a.checks.length)
    .sort((x, y) => ["critical", "high", "medium", "low"].indexOf(x.risk) - ["critical", "high", "medium", "low"].indexOf(y.risk)).slice(0, 5);
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <Panel title="Authentication Posture" meta={`${keys.length} keys total`}>
        <div className="space-y-3">
          <ProgressRow label="Live keys" value={data.summary.liveKeys} total={Math.max(1, keys.length)} tone="ok" right={data.summary.liveKeys} />
          <ProgressRow label="Expiring within 7 days" value={data.summary.renewals} total={Math.max(1, data.summary.accounts)} tone="warn" right={data.summary.renewals} />
          <ProgressRow label="Revoked" value={revoked} total={Math.max(1, keys.length)} tone="info" right={revoked} />
          <p className="rounded-lg border border-info/30 bg-info/5 p-2.5 text-xs text-ink"><b>Recommended posture:</b> short-lived keys rotated before expiry, a named active owner, and the narrowest role that works.</p>
        </div>
      </Panel>
      <Panel title="Lifecycle & Risk Status">
        <div className="space-y-3">
          {(["active", "restricted", "quarantined", "dormant"] as const).map((k) => (
            <ProgressRow key={k} label={STATE[k].label} value={st[k] ?? 0} total={total}
              tone={k === "active" ? "ok" : k === "quarantined" ? "bad" : k === "restricted" ? "warn" : "info"} right={st[k] ?? 0} />
          ))}
        </div>
      </Panel>
      <Panel title="Priority Governance Actions">
        {priority.length ? (
          <ul className="divide-y divide-line text-sm">{priority.map((a) => (
            <li key={a.id} className="flex items-start justify-between gap-2 py-2">
              <button onClick={() => onSelect(a.id)} className="text-left"><b className="block text-ink hover:underline">{a.name}</b>
                <span className="text-xs text-muted">{a.checks.filter((c) => c.status !== "pass").map((c) => c.label).join(" · ") || STATE[a.state].label}</span></button>
              <span className={`text-xs font-bold ${a.risk === "critical" || a.risk === "high" ? "text-bad" : "text-accent-ink"}`}>{a.nextExpiry && a.expiringKeys ? utcDate(a.nextExpiry).split(" · ")[0] : humanize(a.risk)}</span>
            </li>))}</ul>
        ) : <p className="text-sm text-muted">Every machine identity passes its checks.</p>}
      </Panel>
    </div>
  );
}

function CreateForm({ people, onDone }: { people: Assignee[]; onDone: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [role, setRole] = useState(SERVICE_ROLES[0]);
  const [owner, setOwner] = useState("");
  const { busy, error, run } = useMutation();
  return (
    <Panel title="Register service account" meta="A non-Admin role and a named owner are required" action={<Button onClick={onDone}>Cancel</Button>}>
      <form className="grid gap-3 md:grid-cols-4" onSubmit={(e) => { e.preventDefault(); run("create", (t) => createServiceAccount(t, { name, description, role, owner_user_id: owner || people[0]?.id || "" })).then((ok) => ok && onDone()); }}>
        <input required minLength={2} className={inputClass} placeholder="Name, e.g. erp-sync" value={name} onChange={(e) => setName(e.target.value)} aria-label="Name" />
        <input className={inputClass} placeholder="Workload purpose" value={description} onChange={(e) => setDescription(e.target.value)} aria-label="Purpose" />
        <select aria-label="Role" className={inputClass} value={role} onChange={(e) => setRole(e.target.value)}>{SERVICE_ROLES.map((r) => <option key={r}>{r}</option>)}</select>
        <select aria-label="Owner" className={inputClass} value={owner} onChange={(e) => setOwner(e.target.value)}>
          {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <div className="md:col-span-4"><ErrorNote message={error} /></div>
        <div><Button type="submit" variant="primary" busy={busy === "create"}>Register account</Button></div>
      </form>
    </Panel>
  );
}
