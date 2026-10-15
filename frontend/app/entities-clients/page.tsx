"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Briefcase, Building2, Search, ShieldCheck, UserCheck, UserX, ShieldAlert } from "lucide-react";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import {
  Badge, Breadcrumb, Button, DetailRows, EmptyState, ErrorNote, KpiTile, OpsHero, Panel, PillTabs, ProgressRow,
  inputClass, useMutation, utcDate,
} from "@/components/operations/ui";
import { ChecksList } from "@/components/operations/registry";
import {
  addEngagementMember, createEngagement, getAssignees, getEntitiesOverview, revokeEngagementMember,
  type Assignee, type EngagementRow, type EntitiesOverview,
} from "@/lib/api";

type TabKey = "all" | "members" | "revoked" | "entities";
const engId = (rows: EngagementRow[], id: string) => `ENG-${String(rows.findIndex((r) => r.id === id) + 1).padStart(3, "0")}`;

/** Client engagements and their delegated access (F1 engagement model). The
 * legal-entity register stays blocked pending DPIA and Legal/Compliance
 * sign-off; nothing here creates client legal-entity records. */
export default function EntitiesClientsPage() {
  const { data, error, loading, signedOut, reload } = useLiveData(
    "entities", (token, signal) => getEntitiesOverview(token, signal), 30_000,
  );
  const people = useLiveData("ops-assignees", (token, signal) => getAssignees(token, signal), 20_000);
  const [tab, setTab] = useState<TabKey>("all");
  const [selectedId, setSelectedId] = useState("");
  const [creating, setCreating] = useState(false);
  const rows = useMemo(() => data?.engagements ?? [], [data]);
  const selected = rows.find((r) => r.id === selectedId) ?? rows[0];

  return (
    <main className="flex-1 space-y-4 overflow-y-auto p-4">
      <Breadcrumb section="Administration" page="Entities / Clients" detail="Client & legal-entity governance" />
      <OpsHero icon={Building2} title="Entities / Clients"
        subtitle="Govern client organizations, legal entities, ownership, jurisdictions, and delegated access. Entity records ≠ client relationships ≠ tenant authorization.">
        <p className="text-base font-bold text-white">Verified structures. Protected client data.</p>
        <p>Tenant-bound · Relationship-aware</p><p>Framework-specific · Fully traceable</p>
      </OpsHero>
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {data && (
        <>
          <Kpis data={data} />
          <section className="flex flex-col gap-3 rounded-xl border border-accent/40 border-l-4 border-l-accent bg-accent/5 p-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-ink"><b className="text-accent-ink">ENTITY-GOVERNANCE BOUNDARY · DPIA HOLD</b> {data.legalEntityRegister.reason} Client engagements and their delegated access are live; legal-entity records, ownership links and jurisdictions cannot be created until sign-off.</p>
            <Badge tone="warn">Engineering hold</Badge>
          </section>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <PillTabs label="Entity views" active={tab} onChange={setTab} tabs={[
              { key: "all", label: "All engagements", count: rows.length }, { key: "members", label: "Delegated access", count: data.summary.members },
              { key: "revoked", label: "Revoked access", count: data.summary.revoked }, { key: "entities", label: "Legal entities" }]} />
            <div className="flex gap-2">
              <Button disabled title="Blocked pending DPIA and Legal/Compliance sign-off">+ Add legal entity</Button>
              <Button variant="primary" onClick={() => setCreating(true)}>+ Create engagement</Button>
            </div>
          </div>
          {creating && <CreateForm onDone={() => { setCreating(false); reload(); }} />}
          {tab === "entities" ? <LegalEntityHold /> : (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_440px]">
              <Register rows={rows} tab={tab} selectedId={selected?.id} onSelect={setSelectedId} />
              {selected ? <Detail key={selected.id} e={selected} rows={rows} people={people.data ?? []} onChanged={reload} />
                : <Panel title="Client engagement"><EmptyState icon={Briefcase} title="No client engagements yet">Create one to give named people delegated access to a client&apos;s work.</EmptyState></Panel>}
            </div>
          )}
          <Bottom data={data} selected={selected} />
        </>
      )}
    </main>
  );
}

function Kpis({ data }: { data: EntitiesOverview }) {
  const s = data.summary;
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <KpiTile icon={Briefcase} value={s.engagements} label="Client engagements" hint={`${s.active} active`} />
      <KpiTile icon={Building2} tone="warn" value="Hold" label="Legal entities" hint="Register blocked pending DPIA" />
      <KpiTile icon={UserCheck} tone="ok" value={s.members} label="Delegated access" hint="Active engagement members" />
      <KpiTile icon={UserX} value={s.revoked} label="Revoked memberships" hint="Access removed, history kept" />
      <KpiTile icon={ShieldAlert} tone={s.withoutMembers ? "warn" : "ok"} value={s.withoutMembers} label="Engagements without members" hint="Nobody can use them yet" />
    </div>
  );
}

function Register({ rows, tab, selectedId, onSelect }: { rows: EngagementRow[]; tab: TabKey; selectedId?: string; onSelect: (id: string) => void }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const shown = rows.filter((r) => (tab !== "members" || r.activeMembers > 0) && (tab !== "revoked" || r.revokedMembers > 0)
    && (!status || r.status === status)
    && (!query || `${r.name} ${engId(rows, r.id)} ${r.members.map((m) => m.name).join(" ")}`.toLowerCase().includes(query.toLowerCase())));
  return (
    <Panel title="Client engagement register" meta="Tenant-bound · no cross-tenant search">
      <div className="mb-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_10rem_auto]">
        <label className="relative">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input className={`${inputClass} pl-9`} placeholder="Search engagement, ID or member…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <select aria-label="Status" className={inputClass} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>{[...new Set(rows.map((r) => r.status))].map((s) => <option key={s}>{s}</option>)}
        </select>
        <Button onClick={() => { setQuery(""); setStatus(""); }}>Reset</Button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="bg-soft text-xs text-muted">
            <tr>{["Engagement ID / name", "Members", "Operations granted", "Rights version", "Status", "Action"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr>
          </thead>
          <tbody>
            {shown.map((r) => {
              const ops = [...new Set(r.members.filter((m) => m.status === "active").flatMap((m) => m.operations))];
              return (
                <tr key={r.id} className={`border-b border-line ${selectedId === r.id ? "bg-info/5" : ""}`}>
                  <td className="px-3 py-2.5"><b className="block text-ink">{engId(rows, r.id)}</b><span className="text-xs text-muted">{r.name}</span></td>
                  <td className="px-3 py-2.5 text-ink">{r.activeMembers}{r.revokedMembers ? <span className="text-xs text-muted"> · {r.revokedMembers} revoked</span> : null}</td>
                  <td className="px-3 py-2.5 text-xs text-ink">{ops.join(", ") || "—"}</td>
                  <td className="px-3 py-2.5 text-ink">v{r.rightsVersion}</td>
                  <td className="px-3 py-2.5"><Badge tone={r.status === "active" ? "ok" : "neutral"}>{r.status[0].toUpperCase() + r.status.slice(1)}</Badge></td>
                  <td className="px-3 py-2.5"><button aria-label={`Open ${r.name}`} onClick={() => onSelect(r.id)} className="grid h-8 w-8 place-items-center rounded-lg border border-line text-info hover:bg-soft">→</button></td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!shown.length && <EmptyState title={rows.length ? "No engagements match this view" : "No client engagements yet"} />}
      </div>
      <p className="mt-3 flex justify-between text-xs text-muted"><span>{shown.length} of {rows.length} engagements</span><span>One authorized tenant</span></p>
    </Panel>
  );
}

type DetailTab = "profile" | "access" | "entity";

function Detail({ e, rows, people, onChanged }: { e: EngagementRow; rows: EngagementRow[]; people: Assignee[]; onChanged: () => void }) {
  const [tab, setTab] = useState<DetailTab>("profile");
  const { busy, error, run } = useMutation();
  const active = e.members.filter((m) => m.status === "active");
  const done = (ok: boolean) => ok && onChanged();
  return (
    <Panel title={e.name} meta={engId(rows, e.id)} action={<Badge tone={e.status === "active" ? "ok" : "neutral"}>{e.status}</Badge>}>
      <PillTabs label="Engagement detail" active={tab} onChange={setTab} tabs={[
        { key: "profile", label: "Profile" }, { key: "access", label: "Access", count: active.length }, { key: "entity", label: "Legal entity" }]} />
      <div className="mt-4 space-y-4">
        {tab === "profile" && (
          <>
            <DetailRows rows={[
              ["Engagement ID", engId(rows, e.id)], ["Client engagement", e.name], ["Status", e.status],
              ["Rights version", `v${e.rightsVersion}`], ["Active members", active.length],
              ["Revoked memberships", e.revokedMembers], ["Created", e.createdAt ? utcDate(e.createdAt) : "—"],
              ["Legal entity record", "Blocked pending DPIA"],
            ]} />
            <ChecksList title="Readiness gates" checks={[
              { label: "Named engagement", status: "pass", note: e.name },
              { label: "Delegated access granted", status: active.length ? "pass" : "open", note: active.length ? `${active.length} member(s) with explicit grants` : "Nobody can use this engagement yet" },
              { label: "Explicit operation grants", status: active.every((m) => m.operations.length) ? "pass" : "open", note: "Deny by default; each member holds named operations" },
              { label: "Legal entity verified", status: "fail", note: "Blocked pending DPIA and Legal/Compliance sign-off" },
            ]} />
          </>
        )}
        {tab === "access" && (
          <>
            {e.members.length ? (
              <ul className="space-y-2 text-sm">{e.members.map((m) => (
                <li key={m.userId} className="flex items-start justify-between gap-2 rounded-lg border border-line p-2.5">
                  <span><b className="block text-ink">{m.name}</b><span className="text-xs text-muted">{m.operations.join(", ") || "No grants"} · {m.status === "active" ? `granted ${m.grantedAt ? utcDate(m.grantedAt).split(" · ")[0] : ""}` : `revoked ${m.revokedAt ? utcDate(m.revokedAt).split(" · ")[0] : ""}`}</span></span>
                  {m.status === "active" ? <Button variant="danger" busy={busy === m.userId} onClick={() => run(m.userId, (t) => revokeEngagementMember(t, e.id, m.userId)).then(done)}>Revoke</Button>
                    : <Badge tone="neutral">Revoked</Badge>}
                </li>))}</ul>
            ) : <p className="text-sm text-muted">No members yet.</p>}
            <select aria-label="Add member" className={inputClass} value="" disabled={busy === "add"}
              onChange={(ev) => ev.target.value && run("add", (t) => addEngagementMember(t, e.id, ev.target.value)).then(done)}>
              <option value="">Add member with standard grants…</option>
              {people.filter((p) => !active.some((m) => m.userId === p.id)).map((p) => <option key={p.id} value={p.id}>{p.name} · {p.role}</option>)}
            </select>
            <p className="text-xs text-muted">Standard grants: ask, document read/write, model transmit, audit replay, export. Each is checked server-side on every request.</p>
          </>
        )}
        {tab === "entity" && <LegalEntityHold compact />}
        <ErrorNote message={error} />
      </div>
    </Panel>
  );
}

function LegalEntityHold({ compact = false }: { compact?: boolean }) {
  const body = (
    <div className="space-y-3 text-sm text-ink">
      <div className="rounded-lg border border-accent/40 bg-accent/5 p-3">
        <p className="font-bold text-accent-ink">ONBOARDING / ACCESS GATES CLOSED</p>
        <p>Engineering on legal-entity records (names, ownership, parent–subsidiary links, jurisdictions, frameworks) is blocked pending Data Protection Impact Assessment and Legal/Compliance sign-off. No data model exists for them yet.</p>
      </div>
      <ChecksList checks={[
        { label: "Data Protection Impact Assessment", status: "open", note: "Not signed off" },
        { label: "Legal / Compliance sign-off", status: "open", note: "Not signed off" },
        { label: "Legal-entity data model", status: "fail", note: "Not built while the hold is in place" },
      ]} />
    </div>
  );
  return compact ? body : <Panel title="Legal-entity register" meta="Blocked pending DPIA">{body}</Panel>;
}

function Bottom({ data, selected }: { data: EntitiesOverview; selected?: EngagementRow }) {
  const total = Math.max(1, data.summary.engagements);
  return (
    <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
      <Panel title="Engagement lifecycle & assurance">
        <div className="space-y-3">
          <ProgressRow label="Active" value={data.summary.active} total={total} tone="ok" right={data.summary.active} />
          <ProgressRow label="Without members" value={data.summary.withoutMembers} total={total} tone="warn" right={data.summary.withoutMembers} />
          <ProgressRow label="Closed" value={data.summary.engagements - data.summary.active} total={total} tone="info" right={data.summary.engagements - data.summary.active} />
        </div>
      </Panel>
      <Panel title="Client relationship map">
        {selected ? (
          <div className="space-y-2 text-sm">
            <span className="inline-flex items-center gap-2 rounded-lg border border-line bg-soft px-2.5 py-1.5 font-semibold text-ink">{selected.name} <Badge tone="ok">Engagement</Badge></span>
            {selected.members.filter((m) => m.status === "active").map((m) => (
              <div key={m.userId} className="ml-4 flex items-center gap-2"><span className="h-px w-4 bg-line" />
                <span className="rounded-lg border border-line px-2.5 py-1 text-ink">{m.name}</span><Badge tone="info">{m.operations.length} grants</Badge></div>
            ))}
            <p className="text-xs text-muted">A legal-entity hierarchy will appear here once the DPIA hold is lifted.</p>
          </div>
        ) : <p className="text-sm text-muted">Select an engagement.</p>}
      </Panel>
      <Panel title="Tenant & client access safeguards">
        <ChecksList checks={[
          { label: "Tenant boundary enforced by design", status: "pass", note: "Only this tenant's engagements appear" },
          { label: "Client authorization is separate", status: "pass", note: "Team or role membership never implies engagement access" },
          { label: "Deny by default, explicit deny wins", status: "pass", note: "Expired grants and revoked memberships deny" },
          { label: "Legal-entity verification", status: "open", note: "Blocked pending DPIA" },
        ]} />
      </Panel>
      <Panel title="Governed actions">
        <div className="grid grid-cols-2 gap-2">
          <Link href="/users-teams" className="inline-flex min-h-10 items-center justify-center rounded-lg border border-line bg-panel text-sm font-semibold text-info hover:bg-soft">Invite owner</Link>
          <Link href="/roles-permissions" className="inline-flex min-h-10 items-center justify-center rounded-lg border border-line bg-panel text-sm font-semibold text-info hover:bg-soft">Effective access</Link>
          <Link href="/audit-logs" className="inline-flex min-h-10 items-center justify-center rounded-lg border border-line bg-panel text-sm font-semibold text-info hover:bg-soft">Change history</Link>
          <Button disabled title="Blocked pending DPIA"><ShieldCheck size={14} /> Review hierarchy</Button>
        </div>
        <p className="mt-3 text-xs text-muted">Every membership change is checked by the backend and recorded.</p>
      </Panel>
    </div>
  );
}

function CreateForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const { busy, error, run } = useMutation();
  return (
    <Panel title="Create client engagement" meta="Records no client legal-entity data" action={<Button onClick={onDone}>Cancel</Button>}>
      <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); run("c", (t) => createEngagement(t, name)).then((ok) => ok && onDone()); }}>
        <input required className={`${inputClass} max-w-md`} placeholder="Engagement name, e.g. FY26 statutory audit" value={name} onChange={(e) => setName(e.target.value)} aria-label="Engagement name" />
        <Button type="submit" variant="primary" busy={busy === "c"}>Create</Button>
        <div className="w-full"><ErrorNote message={error} /></div>
      </form>
    </Panel>
  );
}
