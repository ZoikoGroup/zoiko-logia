"use client";

import { FormEvent, useMemo, useState } from "react";
import { Clock3, Mail, Search, UserMinus, Users, UsersRound } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import {
  Avatar, Badge, Breadcrumb, Button, DetailRows, EmptyState, ErrorNote, KpiTile, OpsHero, Panel, PillTabs, inputClass,
  timeAgo, useMutation, utcDate,
} from "@/components/operations/ui";
import { ChecksList } from "@/components/operations/registry";
import { BACKEND_ROLES } from "@/lib/roles";
import { setImpersonation } from "@/lib/impersonation";
import {
  createTeam, createUser, getAdminActivity, getUsersOverview, recordAccessReview, resetUserMfa, setUserActive,
  setUserRole, startImpersonation, updateTeam, type ActivityEvent, type MemberRow, type UsersOverview,
} from "@/lib/api";

type TabKey = "members" | "teams" | "invitations" | "lifecycle" | "reviews";
const STATUS: Record<MemberRow["status"], { label: string; tone: "ok" | "warn" | "bad" | "neutral" }> = {
  active: { label: "Active", tone: "ok" }, invited: { label: "Invited", tone: "warn" },
  offboarding: { label: "Offboarding", tone: "bad" }, inactive: { label: "Inactive", tone: "neutral" },
};
const IDENTITY: Record<MemberRow["identity"], { label: string; tone: "ok" | "warn" | "info" | "neutral" }> = {
  mfa: { label: "Password + MFA", tone: "ok" }, password_only: { label: "No MFA", tone: "warn" },
  invite_pending: { label: "Invite pending", tone: "info" }, unknown: { label: "Unknown", tone: "neutral" },
};
const VIEW_AS_MINUTES = [15, 30, 60];

export default function UsersTeamsPage() {
  const { profile } = useAuth();
  const { data, error, loading, signedOut, reload } = useLiveData(
    "users-overview", (token, signal) => getUsersOverview(token, signal), 30_000,
  );
  const [tab, setTab] = useState<TabKey>("members");
  const [selectedId, setSelectedId] = useState("");
  const [form, setForm] = useState<"invite" | "team" | null>(null);
  const members = useMemo(() => data?.members ?? [], [data]);
  const selected = members.find((m) => m.id === selectedId) ?? members.find((m) => m.status === "offboarding") ?? members[0];
  const select = (id: string, t?: TabKey) => { setSelectedId(id); if (t) setTab(t); };

  return (
    <main className="flex-1 space-y-4 overflow-y-auto p-4">
      <Breadcrumb section="Administration" page="Users & Teams" detail={data ? `Live · ${utcDate(data.generatedAt)}` : undefined} />
      <OpsHero icon={UsersRound} title="Users & Teams"
        subtitle="Manage membership, team ownership, invitations, identity lifecycle, and secure offboarding—without bypassing tenant boundaries or access governance.">
        <p><Badge tone="ok">● TENANT-SCOPED · LIVE</Badge></p>
        <p>Identity lifecycle • Teams &amp; ownership</p>
        <p>Least privilege • Auditable changes</p>
      </OpsHero>
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {data && (
        <>
          <Kpis data={data} />
          <section className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-panel p-3">
            <PillTabs label="People views" active={tab} onChange={setTab} tabs={[
              { key: "members", label: "Members", count: members.length }, { key: "teams", label: "Teams", count: data.teams.length },
              { key: "invitations", label: "Invitations", count: data.summary.openInvitations },
              { key: "lifecycle", label: "Lifecycle", count: data.summary.offboardingCases + data.summary.inactive },
              { key: "reviews", label: "Access Reviews", count: data.summary.reviewsDue }]} />
            <div className="flex gap-2">
              <Button onClick={() => setForm("team")}>+ Create Team</Button>
              <Button variant="primary" onClick={() => setForm("invite")}>+ Invite Member</Button>
            </div>
          </section>
          {form === "invite" && <InviteForm onDone={() => { setForm(null); reload(); }} />}
          {form === "team" && <TeamForm members={members} onDone={() => { setForm(null); reload(); }} />}
          {!data.authStatusAvailable && <p className="text-xs text-muted">Sign-in and MFA status could not be read from Supabase Auth right now; those columns show &ldquo;Unknown&rdquo;.</p>}

          {(tab === "members" || tab === "invitations" || tab === "lifecycle") && (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
              <Directory data={data} tab={tab} selectedId={selected?.id} onSelect={(id) => select(id)} selfId={profile?.id} onChanged={reload} />
              {selected ? <Inspector key={selected.id} m={selected} data={data} selfId={profile?.id} onChanged={reload} />
                : <Panel title="Member Lifecycle Inspector"><EmptyState title="Select a member" /></Panel>}
            </div>
          )}
          {tab === "teams" && <TeamsPanel data={data} onChanged={reload} />}
          {tab === "reviews" && <ReviewsPanel data={data} selfId={profile?.id} onChanged={reload} onSelect={(id) => select(id, "members")} />}

          <div className="grid gap-4 xl:grid-cols-3">
            <Panel title="Team Coverage & Ownership" meta={`${data.summary.ownedTeams} of ${data.teams.length} teams owned`}>
              {data.teams.length ? (
                <ul className="space-y-3">
                  {data.teams.map((t) => {
                    const max = Math.max(...data.teams.map((x) => x.members), 1);
                    return (
                      <li key={t.id} className="grid grid-cols-[minmax(0,1fr)_7rem_auto] items-center gap-3 text-sm">
                        <span><b className="block text-ink">{t.name}</b><span className="text-xs text-muted">{t.owner ? `${t.owner} · owner` : "No owner"}</span></span>
                        <span className="h-2 overflow-hidden rounded-full bg-soft"><span className="block h-full rounded-full bg-accent" style={{ width: `${(t.members / max) * 100}%` }} /></span>
                        <span className="text-xs text-muted">{t.members} members</span>
                      </li>
                    );
                  })}
                </ul>
              ) : <p className="text-sm text-muted">No teams yet. Create one to give people an accountable owner.</p>}
            </Panel>
            <Panel title="Lifecycle & Access Priorities" meta="Actionable blockers">
              {data.priorities.length ? (
                <ol className="space-y-3">
                  {data.priorities.map((p, i) => (
                    <li key={p.kind} className="flex gap-3">
                      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-accent/10 text-sm font-bold text-accent-ink">{i + 1}</span>
                      <button onClick={() => select(p.userId, p.kind === "reviews" ? "reviews" : p.kind === "invitations" ? "invitations" : "lifecycle")} className="text-left">
                        <b className="block text-sm text-ink hover:underline">{p.title}</b><span className="text-xs text-muted">{p.detail}</span>
                      </button>
                    </li>
                  ))}
                </ol>
              ) : <p className="text-sm text-muted">Nothing needs attention.</p>}
            </Panel>
            <Panel title="Joiner · Mover · Leaver Controls" meta="Required in production">
              <ChecksList checks={data.controls} />
            </Panel>
          </div>
          <p className="flex items-center gap-3 rounded-xl border border-line bg-panel p-3 text-sm text-ink">
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-hero text-accent"><Users size={16} /></span>
            <span><b>Permission boundary:</b> team membership never grants access by itself. Roles and client-engagement grants do, and the backend checks them on every request.</span>
          </p>
        </>
      )}
    </main>
  );
}

function Kpis({ data }: { data: UsersOverview }) {
  const s = data.summary;
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <KpiTile icon={Users} value={s.activeMembers} label="Active Members" hint="People in this workspace" />
      <KpiTile icon={Mail} tone={s.openInvitations ? "warn" : "ok"} value={s.openInvitations} label="Open Invitations"
        hint={s.staleInvitations ? `${s.staleInvitations} older than 7 days` : "None waiting long"} />
      <KpiTile icon={UsersRound} tone="ok" value={s.activeTeams} label="Active Teams" hint={`${s.ownedTeams} with named owners`} />
      <KpiTile icon={Clock3} tone={s.reviewsDue ? "warn" : "ok"} value={s.reviewsDue} label="Access Reviews Due" hint={`${s.reviewsDueSoon} more due within 7 days`} />
      <KpiTile icon={UserMinus} tone={s.offboardingCases ? "bad" : "ok"} value={s.offboardingCases} label="Offboarding Cases" hint="Deactivated, still owning records" />
    </div>
  );
}

function Directory({ data, tab, selectedId, onSelect, selfId, onChanged }: {
  data: UsersOverview; tab: TabKey; selectedId?: string; onSelect: (id: string) => void; selfId?: string; onChanged: () => void;
}) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [team, setTeam] = useState("");
  const [identity, setIdentity] = useState("");
  const { busy, error, run } = useMutation();
  const base = data.members.filter((m) => tab === "invitations" ? m.status === "invited"
    : tab === "lifecycle" ? !m.isActive : true);
  const rows = base.filter((m) => (!status || m.status === status) && (!team || m.teams.includes(team))
    && (!identity || m.identity === identity)
    && (!query || `${m.name} ${m.email} ${m.role} ${m.teams.join(" ")}`.toLowerCase().includes(query.toLowerCase())));
  return (
    <Panel title={tab === "invitations" ? "Open Invitations" : tab === "lifecycle" ? "Deactivated & Offboarding" : "Member Directory"}
      meta="Directory metadata only · backend authorization required">
      <div className="mb-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_auto]">
        <label className="relative">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input className={`${inputClass} pl-9`} placeholder="Search members by name, team, role, or email…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <Button onClick={() => { setQuery(""); setStatus(""); setTeam(""); setIdentity(""); }}>Reset</Button>
      </div>
      <div className="mb-3 grid gap-2 sm:grid-cols-3">
        <select aria-label="Member status" className={inputClass} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>{Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
        <select aria-label="Team" className={inputClass} value={team} onChange={(e) => setTeam(e.target.value)}>
          <option value="">All teams</option>{data.teams.map((t) => <option key={t.id}>{t.name}</option>)}
        </select>
        <select aria-label="Identity assurance" className={inputClass} value={identity} onChange={(e) => setIdentity(e.target.value)}>
          <option value="">All identities</option>{Object.entries(IDENTITY).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
      </div>
      <ErrorNote message={error} />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-left text-sm">
          <thead className="bg-soft text-xs text-muted">
            <tr>{["Member", "Team", "Assigned role", "Identity", "Status", "Last sign-in"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((m) => {
              const isSelf = m.id === selfId;
              const known = BACKEND_ROLES.includes(m.role);
              return (
                <tr key={m.id} onClick={() => onSelect(m.id)} aria-selected={selectedId === m.id}
                  className={`cursor-pointer border-b border-line hover:bg-soft ${selectedId === m.id ? "bg-accent/5" : ""}`}>
                  <td className="px-3 py-2.5"><span className="flex items-center gap-2"><Avatar name={m.name} />
                    <span><b className="block text-ink">{m.name}{isSelf && <span className="ml-1 font-normal text-muted">(you)</span>}</b><span className="text-xs text-muted">{m.email}</span></span></span></td>
                  <td className="px-3 py-2.5 text-ink">{m.teams.join(", ") || <span className="text-muted">—</span>}</td>
                  <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                    {isSelf || !m.isActive ? <span className="text-ink">{m.role}</span> : (
                      <select aria-label={`Role for ${m.name}`} className={`${inputClass} min-h-8 py-1`} value={m.role} disabled={busy === m.id}
                        onChange={(e) => run(m.id, (t) => setUserRole(t, m.id, e.target.value)).then((ok) => ok && onChanged())}>
                        {!known && <option value={m.role} disabled>{m.role} (no permissions)</option>}
                        {BACKEND_ROLES.map((r) => <option key={r}>{r}</option>)}
                      </select>
                    )}
                  </td>
                  <td className="px-3 py-2.5"><Badge tone={IDENTITY[m.identity].tone}>{IDENTITY[m.identity].label}</Badge></td>
                  <td className="px-3 py-2.5"><Badge tone={STATUS[m.status].tone}>{STATUS[m.status].label}</Badge></td>
                  <td className="px-3 py-2.5 text-ink">{m.lastSignInAt ? utcDate(m.lastSignInAt) : "Never"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!rows.length && <EmptyState title={tab === "invitations" ? "No open invitations" : tab === "lifecycle" ? "No deactivated accounts" : "No members match these filters"} />}
      </div>
      <p className="mt-3 text-xs text-muted">{rows.length} of {data.members.length} people shown</p>
    </Panel>
  );
}

type InspectorTab = "overview" | "scope" | "lifecycle" | "activity";

function Inspector({ m, data, selfId, onChanged }: { m: MemberRow; data: UsersOverview; selfId?: string; onChanged: () => void }) {
  const [tab, setTab] = useState<InspectorTab>(m.status === "offboarding" ? "lifecycle" : "overview");
  const [note, setNote] = useState("");
  const [viewAs, setViewAs] = useState(false);
  const [reason, setReason] = useState("");
  const [minutes, setMinutes] = useState(30);
  const [events, setEvents] = useState<ActivityEvent[] | null>(null);
  const { busy, error, run } = useMutation();
  const isSelf = m.id === selfId;
  const openBlockers = m.offboardingGates.filter((g) => g.status !== "pass").length;
  const act = (key: string, fn: (t: string) => Promise<unknown>) => run(key, fn).then((ok) => { if (ok) { setNote(""); onChanged(); } });

  async function startViewAs(e: FormEvent) {
    e.preventDefault();
    await run("viewas", async (t) => {
      const session = await startImpersonation(t, { target_user_id: m.id, reason, minutes });
      setImpersonation({ sessionId: session.id, targetName: session.target_name, targetRole: session.target_role, expiresAt: session.expires_at });
      window.location.assign("/");
    });
  }

  return (
    <Panel title="Member Lifecycle Inspector" action={<Badge tone={STATUS[m.status].tone}>{STATUS[m.status].label}</Badge>}>
      <div className="mb-3 flex items-center gap-3">
        <span className="grid h-12 w-12 place-items-center rounded-xl bg-accent text-lg font-bold text-white">{m.name.split(" ").map((p) => p[0]).slice(0, 2).join("")}</span>
        <div><p className="text-lg font-extrabold text-ink">{m.name}</p><p className="text-xs text-muted">{m.email}</p></div>
      </div>
      <PillTabs label="Member detail" active={tab} onChange={(t) => { setTab(t); if (t === "activity" && events === null) run("activity", async (tok) => setEvents(await getAdminActivity(tok, m.id))); }}
        tabs={[{ key: "overview", label: "Overview" }, { key: "scope", label: "Team & Scope" }, { key: "lifecycle", label: "Lifecycle" }, { key: "activity", label: "Activity" }]} />
      <div className="mt-4 space-y-4">
        {m.status === "offboarding" && (
          <div className="rounded-lg border border-accent/40 bg-accent/5 p-3">
            <p className="text-sm font-bold text-accent-ink">OFFBOARDING · COMPLETION BLOCKED</p>
            <p className="text-sm text-ink">{openBlockers} check(s) open. Reassign or revoke what this account still owns before the identity is fully deprovisioned.</p>
          </div>
        )}
        {tab === "overview" && (
          <DetailRows rows={[
            ["Account status", STATUS[m.status].label], ["Role", m.role + (m.privileged ? " · privileged" : "")],
            ["Teams", m.teams.join(", ") || "None"], ["Identity assurance", IDENTITY[m.identity].label],
            ["Sign-in methods", m.providers.length ? m.providers.join(", ") : "—"],
            ["Last sign-in", m.lastSignInAt ? `${utcDate(m.lastSignInAt)} (${timeAgo(m.lastSignInAt)})` : "Never"],
            ["Joined", m.createdAt ? utcDate(m.createdAt).split(" · ")[0] : "—"],
            ["Access review", m.lastReview ? `${m.lastReview.decision} by ${m.lastReview.reviewer}` : "Never reviewed"],
            ["Next review due", `${utcDate(m.reviewDueAt).split(" · ")[0]}${m.reviewOverdue ? " · overdue" : ""}`],
          ]} />
        )}
        {tab === "scope" && (
          <div className="space-y-2 text-sm text-ink">
            <p><b>Role:</b> {m.role}</p>
            <p><b>Teams:</b> {m.teams.join(", ") || "None"}</p>
            <p className="text-xs text-muted">Client data access comes from engagement membership (Entities/Clients), not from teams.</p>
          </div>
        )}
        {tab === "lifecycle" && (m.isActive
          ? <p className="text-sm text-muted">Active account. Offboarding checks appear here once the account is deactivated.</p>
          : <ChecksList title="Offboarding completion gates" checks={m.offboardingGates} />)}
        {tab === "lifecycle" && m.blockers.length > 0 && (
          <ul className="list-disc pl-5 text-xs text-ink">{m.blockers.map((b, i) => <li key={i}>{b.label}</li>)}</ul>
        )}
        {tab === "activity" && (events === null ? <p className="text-sm text-muted">Loading…</p> : events.length ? (
          <ul className="space-y-2 text-sm">{events.map((e) => (
            <li key={e.id}><b className="text-ink">{e.event.replace(/[._]/g, " ")}</b> <span className="text-xs text-muted">· {e.actor} · {utcDate(e.at)}</span></li>))}
          </ul>) : <p className="text-sm text-muted">No recorded identity events.</p>)}
        <ErrorNote message={error} />
        {!isSelf && (
          <div className="space-y-2 border-t border-line pt-3">
            {m.isActive && <input className={inputClass} placeholder="Review note (required to record a change)" value={note} onChange={(e) => setNote(e.target.value)} />}
            <div className="flex flex-wrap gap-2">
              {m.isActive && <Button variant="primary" busy={busy === "review"} onClick={() => act("review", (t) => recordAccessReview(t, { user_id: m.id, decision: "certified", note }))}>Certify access</Button>}
              {m.isActive && m.role !== "Admin" && <Button onClick={() => setViewAs((v) => !v)}>View as</Button>}
              {m.isActive && <Button busy={busy === "mfa"} onClick={() => window.confirm(`Remove ${m.name}'s authenticator apps and sign them out everywhere?`) && act("mfa", (t) => resetUserMfa(t, m.id))}>Reset MFA</Button>}
              <Button variant={m.isActive ? "danger" : "secondary"} busy={busy === "active"} onClick={() => act("active", (t) => setUserActive(t, m.id, !m.isActive))}>
                {m.isActive ? "Deactivate" : "Reactivate"}
              </Button>
              {!m.isActive && <Button disabled={openBlockers > 0} title={openBlockers ? "Reassign every owned record first" : "Nothing left to reassign"}
                busy={busy === "complete"} onClick={() => act("complete", (t) => recordAccessReview(t, { user_id: m.id, decision: "deactivated", note: "Offboarding complete" }))}>Complete offboarding</Button>}
            </div>
            {viewAs && (
              <form onSubmit={startViewAs} className="grid gap-2 sm:grid-cols-[1fr_auto_auto]">
                <input required className={inputClass} placeholder="Reason (recorded in the audit log)" value={reason} onChange={(e) => setReason(e.target.value)} />
                <select aria-label="View-as duration" className={inputClass} value={minutes} onChange={(e) => setMinutes(Number(e.target.value))}>
                  {VIEW_AS_MINUTES.map((x) => <option key={x} value={x}>{x} minutes</option>)}
                </select>
                <Button type="submit" busy={busy === "viewas"}>Start read-only view</Button>
              </form>
            )}
          </div>
        )}
        <p className="text-xs text-muted">Every change is checked by the backend and written to the audit ledger. {data.summary.inactive} deactivated account(s) in this workspace.</p>
      </div>
    </Panel>
  );
}

function TeamsPanel({ data, onChanged }: { data: UsersOverview; onChanged: () => void }) {
  const { busy, error, run } = useMutation();
  const people = data.members.filter((m) => m.isActive);
  return (
    <Panel title="Teams" meta="Named accountable owners · membership grants no access by itself">
      <ErrorNote message={error} />
      {data.teams.length ? (
        <div className="grid gap-3 lg:grid-cols-2">
          {data.teams.map((t) => (
            <div key={t.id} className="rounded-lg border border-line p-3">
              <div className="flex items-start justify-between gap-2">
                <div><p className="font-bold text-ink">{t.name}</p><p className="text-xs text-muted">{t.description || "No description"}</p></div>
                <Badge tone={t.owner ? "ok" : "warn"}>{t.owner ? `Owner: ${t.owner}` : "No owner"}</Badge>
              </div>
              <ul className="my-2 flex flex-wrap gap-1.5">
                {t.memberIds.map((id) => {
                  const p = data.members.find((m) => m.id === id);
                  return <li key={id} className="flex items-center gap-1 rounded-full bg-soft px-2 py-0.5 text-xs text-ink">{p?.name ?? id}
                    <button aria-label={`Remove ${p?.name}`} className="text-muted hover:text-bad" onClick={() => run(`rm-${id}`, (tok) => updateTeam(tok, t.id, { remove: [id] })).then((ok) => ok && onChanged())}>×</button></li>;
                })}
                {!t.memberIds.length && <li className="text-xs text-muted">No members</li>}
              </ul>
              <div className="grid grid-cols-2 gap-2">
                <select aria-label={`Add member to ${t.name}`} className={inputClass} value="" disabled={busy === `add-${t.id}`}
                  onChange={(e) => e.target.value && run(`add-${t.id}`, (tok) => updateTeam(tok, t.id, { add: [e.target.value] })).then((ok) => ok && onChanged())}>
                  <option value="">Add member…</option>{people.filter((p) => !t.memberIds.includes(p.id)).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
                <select aria-label={`Owner of ${t.name}`} className={inputClass} value={t.ownerId ?? ""} disabled={busy === `own-${t.id}`}
                  onChange={(e) => e.target.value && run(`own-${t.id}`, (tok) => updateTeam(tok, t.id, { owner_user_id: e.target.value })).then((ok) => ok && onChanged())}>
                  <option value="">Set owner…</option>{people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </div>
            </div>
          ))}
        </div>
      ) : <EmptyState icon={UsersRound} title="No teams yet">Create a team to group people under an accountable owner.</EmptyState>}
    </Panel>
  );
}

function ReviewsPanel({ data, selfId, onChanged, onSelect }: { data: UsersOverview; selfId?: string; onChanged: () => void; onSelect: (id: string) => void }) {
  const { busy, error, run } = useMutation();
  const rows = data.members.filter((m) => m.isActive).sort((a, b) => a.reviewDueAt.localeCompare(b.reviewDueAt));
  return (
    <Panel title="Access Reviews" meta="Privileged roles monthly · other roles quarterly · never self-certified">
      <ErrorNote message={error} />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="bg-soft text-xs text-muted"><tr>{["Member", "Role", "Last review", "Due", ""].map((h) => <th key={h} className="px-3 py-2">{h}</th>)}</tr></thead>
          <tbody>{rows.map((m) => (
            <tr key={m.id} className="border-b border-line">
              <td className="px-3 py-2"><button onClick={() => onSelect(m.id)} className="font-semibold text-ink hover:underline">{m.name}</button></td>
              <td className="px-3 py-2 text-ink">{m.role}{m.privileged && <span className="ml-1 text-[10px] text-muted">privileged</span>}</td>
              <td className="px-3 py-2 text-ink">{m.lastReview ? `${utcDate(m.lastReview.at).split(" · ")[0]} · ${m.lastReview.reviewer}` : "Never"}</td>
              <td className="px-3 py-2"><Badge tone={m.reviewOverdue ? "bad" : "ok"}>{m.reviewOverdue ? "Overdue" : utcDate(m.reviewDueAt).split(" · ")[0]}</Badge></td>
              <td className="px-3 py-2 text-right">{m.id === selfId ? <span className="text-xs text-muted">Another Admin reviews you</span> :
                <Button busy={busy === m.id} onClick={() => run(m.id, (t) => recordAccessReview(t, { user_id: m.id, decision: "certified", note: "" })).then((ok) => ok && onChanged())}>Certify</Button>}</td>
            </tr>))}</tbody>
        </table>
      </div>
    </Panel>
  );
}

function InviteForm({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<string>(BACKEND_ROLES[0]);
  const [sendInvite, setSendInvite] = useState(true);
  const [password, setPassword] = useState("");
  const [notice, setNotice] = useState("");
  const { busy, error, run } = useMutation();
  return (
    <Panel title="Invite member" meta="Only roles the backend registry knows can be assigned" action={<Button onClick={onDone}>Close</Button>}>
      <form className="grid gap-3 md:grid-cols-4" onSubmit={(e) => {
        e.preventDefault();
        run("invite", async (t) => {
          const created = await createUser(t, { email, full_name: fullName, role, ...(sendInvite ? {} : { password }) });
          setNotice(created.invited ? `Invitation sent to ${created.email}.` : `${created.full_name} was added. Share the temporary password securely.`);
          setEmail(""); setFullName(""); setPassword("");
        });
      }}>
        <input required className={inputClass} placeholder="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} aria-label="Full name" />
        <input required type="email" className={inputClass} placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} aria-label="Email" />
        <select aria-label="Role" className={inputClass} value={role} onChange={(e) => setRole(e.target.value)}>{BACKEND_ROLES.map((r) => <option key={r}>{r}</option>)}</select>
        {sendInvite ? <p className="self-center text-xs text-muted">They&apos;ll choose their own password from the email.</p>
          : <input required type="password" autoComplete="new-password" className={inputClass} placeholder="Temporary password" value={password} onChange={(e) => setPassword(e.target.value)} aria-label="Temporary password" />}
        <label className="flex items-center gap-2 text-sm text-ink md:col-span-2"><input type="checkbox" checked={sendInvite} onChange={(e) => setSendInvite(e.target.checked)} /> Send invitation email (recommended)</label>
        <div className="flex items-center gap-3 md:col-span-2">
          <Button type="submit" variant="primary" busy={busy === "invite"}>{sendInvite ? "Send invitation" : "Add member"}</Button>
          {notice && <span role="status" className="text-sm text-ok">{notice}</span>}
        </div>
        <div className="md:col-span-4"><ErrorNote message={error} /></div>
      </form>
    </Panel>
  );
}

function TeamForm({ members, onDone }: { members: MemberRow[]; onDone: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [owner, setOwner] = useState("");
  const { busy, error, run } = useMutation();
  return (
    <Panel title="Create team" action={<Button onClick={onDone}>Cancel</Button>}>
      <form className="grid gap-3 md:grid-cols-3" onSubmit={(e) => { e.preventDefault(); run("team", (t) => createTeam(t, { name, description, owner_user_id: owner || null })).then((ok) => ok && onDone()); }}>
        <input required minLength={2} className={inputClass} placeholder="Team name" value={name} onChange={(e) => setName(e.target.value)} aria-label="Team name" />
        <input className={inputClass} placeholder="Purpose (optional)" value={description} onChange={(e) => setDescription(e.target.value)} aria-label="Purpose" />
        <select aria-label="Owner" className={inputClass} value={owner} onChange={(e) => setOwner(e.target.value)}>
          <option value="">Owner (optional)</option>{members.filter((m) => m.isActive).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
        </select>
        <div className="md:col-span-3"><ErrorNote message={error} /></div>
        <div><Button type="submit" variant="primary" busy={busy === "team"}>Create team</Button></div>
      </form>
    </Panel>
  );
}
