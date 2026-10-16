"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import {
  AlertTriangle, Briefcase, CalendarRange, CheckCircle2, ClipboardCheck, Download, FileText, FolderKanban, Link2,
  Plus, Send, ShieldCheck, Sparkles, Trash2, Undo2, UserCheck, UserX,
} from "lucide-react";
import {
  Badge, Btn, Callout, CheckRow, Checklist, ControlNote, DateCell, Empty, ErrorNote, FilterTabs, Hero, HeroButton, InfoCards,
  Inspector, KeyGrid, ListItem, Loading, Panel, Readiness, RegisterHead, RegisterRow, ScopeBar, SearchField, Stack,
  StatCard, StatGrid, WorkflowPage, inputClass, shortId, type CheckState, type Tone,
} from "@/components/workflow-ui/kit";
import { getAuthToken, listDrafts, listEngagements, listKritonAttachments, listSavedAnswers, type Engagement } from "@/lib/api";
import {
  addWorkpaperItem, createWorkpaper, downloadWorkpaperPack, getWorkpaper, listReviewers, listWorkpapers, removeWorkpaperItem,
  reviewWorkpaper, submitWorkpaper, updateWorkpaper, type Reviewer, type Workpaper, type WorkpaperItemKind, type WorkpaperStatus,
} from "@/lib/workpapers-api";

const STATUS: Record<WorkpaperStatus, { label: string; tone: Tone }> = {
  open: { label: "In preparation", tone: "neutral" },
  in_review: { label: "Awaiting review", tone: "info" },
  signed_off: { label: "Signed & locked", tone: "ok" },
};
const KIND_LABEL: Record<WorkpaperItemKind, string> = { saved_answer: "Saved answer", draft: "Draft", document: "Document" };
type Option = { kind: WorkpaperItemKind; id: string; title: string };
type Tab = "all" | "open" | "in_review" | "mine" | "signed_off";
const TEMPLATE = "md:grid-cols-[minmax(0,2.3fr)_minmax(0,1.2fr)_minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,0.6fr)]";

/** The sign-off checks a workpaper passes, read from the record itself. */
function checks(wp: Workpaper): { title: string; detail: string; state: CheckState }[] {
  const items = wp.items ?? [];
  const missing = items.filter((i) => i.missing).length;
  const submitted = wp.status !== "open";
  return [
    { title: "Purpose & scope", detail: wp.engagementName ? `Client job ${wp.engagementName}${wp.period ? ` · ${wp.period}` : ""}` : "No client job linked", state: wp.engagementName ? "pass" : "warn" },
    { title: "Supporting evidence", detail: items.length ? `${items.length} item${items.length === 1 ? "" : "s"} attached` : "Nothing attached yet", state: items.length ? "pass" : "warn" },
    { title: "Evidence still available", detail: missing ? `${missing} attached item${missing === 1 ? " was" : "s were"} deleted` : "Every attached item still exists", state: !items.length ? "todo" : missing ? "fail" : "pass" },
    { title: "Independent reviewer", detail: wp.reviewerName ? `${wp.reviewerName} (not the preparer)` : "Not chosen", state: wp.reviewerId ? "pass" : "warn" },
    { title: "Preparer conclusion", detail: submitted ? "Submitted for review" : "Not yet submitted", state: submitted ? "pass" : "todo" },
    { title: "Independent sign-off", detail: wp.signedOffAt ? `Signed by ${wp.signedOffBy}` : "Not yet signed off", state: wp.status === "signed_off" ? "pass" : "todo" },
  ];
}

export default function WorkpapersPage() {
  const [workpapers, setWorkpapers] = useState<Workpaper[]>([]);
  const [selected, setSelected] = useState<Workpaper | null>(null);
  const [engagements, setEngagements] = useState<Engagement[]>([]);
  const [reviewers, setReviewers] = useState<Reviewer[]>([]);
  const [options, setOptions] = useState<Option[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState("");
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<Tab>("all");
  const [client, setClient] = useState("");
  const [period, setPeriod] = useState("");
  const [reviewerScope, setReviewerScope] = useState("");
  const [form, setForm] = useState({ title: "", period: "", engagement_id: "", reviewer_id: "" });
  const [notes, setNotes] = useState("");
  const [reviewNote, setReviewNote] = useState("");
  const [pick, setPick] = useState("");
  const titleInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const token = getAuthToken();
    Promise.all([listWorkpapers(), listEngagements(token), listReviewers()])
      .then(([w, e, r]) => { setWorkpapers(w); setEngagements(e); setReviewers(r); })
      .catch(() => setError("Could not load workpapers from the server."))
      .finally(() => setLoading(false));
    Promise.all([listSavedAnswers(token), listDrafts(token), listKritonAttachments(token)])
      .then(([answers, drafts, documents]) => setOptions([
        ...answers.map((a) => ({ kind: "saved_answer" as const, id: a.id, title: a.query_text })),
        ...drafts.map((d) => ({ kind: "draft" as const, id: d.id, title: d.title })),
        ...documents.map((d) => ({ kind: "document" as const, id: d.id, title: d.filename })),
      ]))
      .catch(() => setOptions([]));
  }, []);

  function show(wp: Workpaper) {
    setSelected(wp);
    setNotes(wp.notes ?? "");
    setReviewNote("");
    setActionError("");
    setWorkpapers((prev) => prev.map((w) => (w.id === wp.id ? { ...w, ...wp } : w)));
  }

  async function run(label: string, action: () => Promise<Workpaper | void>) {
    setBusy(label);
    setActionError("");
    try {
      const result = await action();
      if (result) show(result);
    } catch (err) {
      setActionError((err instanceof Error && err.message) || "That did not work.");
    } finally {
      setBusy("");
    }
  }

  async function open(id: string) {
    await run("open", () => getWorkpaper(id));
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!form.title.trim()) return;
    await run("create", async () => {
      const wp = await createWorkpaper({ ...form, engagement_id: form.engagement_id || null, reviewer_id: form.reviewer_id || null });
      setWorkpapers((prev) => [wp, ...prev]);
      setForm({ title: "", period: "", engagement_id: "", reviewer_id: "" });
      return wp;
    });
  }

  const needle = query.trim().toLowerCase();
  const scoped = workpapers.filter((w) => (!client || w.engagementId === client) && (!period || w.period === period)
    && (!reviewerScope || w.reviewerId === reviewerScope));
  const inTab = (w: Workpaper) => tab === "all" || (tab === "mine" ? w.canReview : w.status === tab);
  const visible = scoped.filter((w) => inTab(w)
    && (!needle || w.title.toLowerCase().includes(needle) || (w.engagementName ?? "").toLowerCase().includes(needle)));
  const attached = new Set((selected?.items ?? []).map((i) => `${i.kind}:${i.itemId}`));
  const available = options.filter((o) => !attached.has(`${o.kind}:${o.id}`));
  const periods = [...new Set(workpapers.map((w) => w.period).filter(Boolean))].sort();
  const count = (status: WorkpaperStatus) => scoped.filter((w) => w.status === status).length;
  const unsigned = scoped.filter((w) => w.status !== "signed_off");
  const exceptions = [
    ...unsigned.filter((w) => w.itemCount === 0).map((w) => ({ w, title: "No supporting evidence", tone: "warn" as const, badge: "Evidence" })),
    ...unsigned.filter((w) => !w.reviewerId).map((w) => ({ w, title: "No independent reviewer", tone: "bad" as const, badge: "Reviewer" })),
  ];
  const reviewQueue = scoped.filter((w) => w.status === "in_review" || w.status === "signed_off")
    .sort((a, b) => (b.updatedAt ?? "").localeCompare(a.updatedAt ?? ""));
  const gate = selected ? checks(selected) : [];
  const blocker = gate.find((c) => c.state === "fail" || c.state === "warn");

  return (
    <WorkflowPage section="Accounting Workflows" title="Workpapers" subtitle="Prepare, substantiate, and independently review accounting conclusions.">
      <ScopeBar items={[
        { icon: Briefcase, label: "Client / entity", value: client, onChange: setClient,
          options: [{ value: "", label: "All client jobs" }, ...engagements.map((e) => ({ value: e.id, label: e.name }))] },
        { icon: CalendarRange, label: "Reporting period", value: period, onChange: setPeriod,
          options: [{ value: "", label: "All periods" }, ...periods.map((p) => ({ value: p, label: p }))] },
        { icon: UserCheck, label: "Assigned reviewer", value: reviewerScope, onChange: setReviewerScope,
          options: [{ value: "", label: "All reviewers" }, ...reviewers.map((r) => ({ value: r.id, label: r.name }))] },
      ]} />

      <Hero icon={FolderKanban} eyebrow="Controlled accounting evidence · Human sign-off" title="Every conclusion. Supported. Reviewed. Traceable."
        subtitle="Answers, drafts, documents and the reviewer's decision in one defensible job file."
        actions={<>
          <HeroButton href="/ask-kriton"><Sparkles size={13} /> Assist with Kriton</HeroButton>
          <HeroButton primary onClick={() => titleInput.current?.focus()}><Plus size={13} /> New workpaper</HeroButton>
        </>} />

      {error && <ErrorNote message={error} />}

      <StatGrid>
        <StatCard icon={FileText} tone="info" value={count("open") + count("in_review")} label="Active workpapers" hint="In preparation or review" />
        <StatCard icon={ClipboardCheck} tone="warn" value={count("in_review")} label="Awaiting review" hint="With the assigned reviewer" />
        <StatCard icon={AlertTriangle} tone="bad" value={unsigned.filter((w) => w.itemCount === 0).length} label="Evidence gaps" hint="Open with nothing attached" />
        <StatCard icon={UserX} tone="neutral" value={unsigned.filter((w) => !w.reviewerId).length} label="Reviewer not chosen" hint="Cannot be submitted yet" />
        <StatCard icon={CheckCircle2} tone="ok" value={count("signed_off")} label="Signed & locked" hint="Independent sign-off recorded" />
      </StatGrid>

      {loading ? <Loading>Loading workpapers…</Loading> : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
          <div className="min-w-0 space-y-4">
            <Panel title="Workpaper register" subtitle="Accounting working papers, their evidence and review assignments">
              <form onSubmit={handleCreate} className="mb-3 grid gap-2 rounded-lg border border-dashed border-line bg-soft/50 p-2.5 md:grid-cols-[2fr_1fr_1.4fr_1.4fr_auto]">
                <input ref={titleInput} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="New workpaper title, e.g. Revenue recognition FY26"
                  aria-label="Workpaper title" className={inputClass} />
                <input value={form.period} onChange={(e) => setForm({ ...form, period: e.target.value })} placeholder="Period, e.g. FY2026"
                  aria-label="Period" className={inputClass} />
                <select value={form.engagement_id} onChange={(e) => setForm({ ...form, engagement_id: e.target.value })} aria-label="Client job" className={inputClass}>
                  <option value="">No client job</option>
                  {engagements.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
                </select>
                <select value={form.reviewer_id} onChange={(e) => setForm({ ...form, reviewer_id: e.target.value })} aria-label="Reviewer" className={inputClass}>
                  <option value="">Reviewer (choose later)</option>
                  {reviewers.map((r) => <option key={r.id} value={r.id}>{r.name} · {r.role}</option>)}
                </select>
                <Btn type="submit" variant="primary" disabled={!!busy || !form.title.trim()}><Plus size={13} /> {busy === "create" ? "Creating…" : "Create"}</Btn>
              </form>

              <FilterTabs label="Filter workpapers" active={tab} onChange={setTab} tabs={[
                { key: "all", label: "All workpapers", count: scoped.length },
                { key: "open", label: "In preparation", count: count("open") },
                { key: "in_review", label: "In review", count: count("in_review") },
                { key: "mine", label: "For my review", count: scoped.filter((w) => w.canReview).length },
                { key: "signed_off", label: "Locked", count: count("signed_off") },
              ]} />
              <div className="my-3 flex gap-2">
                <SearchField value={query} onChange={setQuery} placeholder="Search workpaper title or client job…" label="Search workpapers" />
              </div>

              {visible.length === 0 ? (
                <Empty icon={FolderKanban} title={workpapers.length ? "No workpapers match" : "No workpapers yet"}>
                  {workpapers.length ? "Change the scope, tab or search." : "Create one with the form above."}
                </Empty>
              ) : (
                <div className="overflow-hidden rounded-lg border border-line">
                  <RegisterHead template={TEMPLATE} columns={["Workpaper / reference", "Preparer & reviewer", "Evidence", "Gate status", "Updated"]} />
                  {visible.map((w) => (
                    <RegisterRow key={w.id} template={TEMPLATE} selected={selected?.id === w.id} onClick={() => void open(w.id)}
                      icon={FileText} tone={w.status === "signed_off" ? "ok" : w.itemCount === 0 ? "warn" : "info"}
                      title={w.title} subtitle={[shortId("WP", w.id), w.engagementName, w.period].filter(Boolean).join(" · ")}
                      cells={[
                        <Stack key="p" main={w.ownerName ?? "—"} sub={w.reviewerName ? `Review: ${w.reviewerName}` : "Reviewer not chosen"} subTone={w.reviewerName ? "muted" : "warn"} />,
                        <Stack key="e" main={`${w.itemCount} linked`} sub={w.itemCount ? "Answers, drafts, documents" : "No evidence attached"} subTone={w.itemCount ? "muted" : "warn"} />,
                        <Badge key="s" tone={STATUS[w.status].tone}>{STATUS[w.status].label}</Badge>,
                        <DateCell key="d" iso={w.updatedAt ?? w.createdAt} />,
                      ]} />
                  ))}
                </div>
              )}
              <p className="mt-2 text-[11px] text-muted">{visible.length} of {workpapers.length} workpapers shown</p>
            </Panel>

            <div className="grid gap-4 md:grid-cols-2">
              <Panel title="Exceptions needing resolution">
                {exceptions.length === 0 ? <p className="py-3 text-xs text-muted">No open exceptions.</p> : (
                  <ul>{exceptions.slice(0, 5).map(({ w, title, tone, badge }) => (
                    <ListItem key={`${badge}:${w.id}`} icon={AlertTriangle} tone={tone} title={title}
                      detail={`${w.title} · ${shortId("WP", w.id)}`} badge={<Badge tone={tone}>{badge}</Badge>} onClick={() => void open(w.id)} />
                  ))}</ul>
                )}
              </Panel>
              <Panel title="Reviewer actions">
                {reviewQueue.length === 0 ? <p className="py-3 text-xs text-muted">Nothing submitted for review yet.</p> : (
                  <ul>{reviewQueue.slice(0, 5).map((w) => (
                    <ListItem key={w.id} icon={w.status === "signed_off" ? CheckCircle2 : Send} tone={w.status === "signed_off" ? "ok" : "info"}
                      title={w.status === "signed_off" ? "Signed off" : "Awaiting review"}
                      detail={`${w.title} · ${w.reviewerName ?? "reviewer"}`} badge={<Badge tone={STATUS[w.status].tone}>{w.status === "signed_off" ? "Ready" : "In review"}</Badge>}
                      onClick={() => void open(w.id)} />
                  ))}</ul>
                )}
              </Panel>
            </div>
          </div>

          {!selected ? (
            <section className="rounded-xl border border-line bg-panel p-4 shadow-[0_4px_14px_rgba(13,34,64,0.05)]" aria-label="Workpaper inspector">
              <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted">Workpaper inspector</p>
              <Empty icon={FolderKanban} title="Select a workpaper">Pick a workpaper to see its evidence, checks and review status.</Empty>
            </section>
          ) : (
            <Inspector eyebrow={`Workpaper inspector · ${shortId("WP", selected.id)}`} title={selected.title}
              badges={<>
                <Badge tone={STATUS[selected.status].tone}>{STATUS[selected.status].label}</Badge>
                {!(selected.items ?? []).length && selected.status !== "signed_off" && <Badge tone="warn">Evidence gap</Badge>}
                {selected.period && <Badge>{selected.period}</Badge>}
              </>}
              description="Period-end working paper: the evidence behind the conclusion, the preparer's notes and the independent reviewer's decision.">
              <KeyGrid items={[
                ["Preparer", selected.ownerName ?? "—"],
                ["Reviewer", selected.reviewerName ?? "Not chosen"],
                ["Client job", selected.engagementName ?? "None"],
                ["Period", selected.period || "—"],
              ]} />

              <Readiness label="Workpaper readiness" passed={gate.filter((c) => c.state === "pass").length} total={gate.length}
                hint="Readiness is a checklist indicator, not accounting approval." />

              {selected.status === "signed_off" ? (
                <Callout tone="ok" title="Signed off and locked">{selected.signedOffBy} on {selected.signedOffAt ? new Date(selected.signedOffAt).toLocaleString() : "—"}</Callout>
              ) : blocker ? (
                <Callout tone={blocker.state === "fail" ? "bad" : "warn"} title="Review gate blocked">{blocker.title}: {blocker.detail}.</Callout>
              ) : null}

              {selected.reviewNote && selected.status !== "in_review" && (
                <Callout tone={selected.status === "signed_off" ? "info" : "warn"} title="Reviewer note">{selected.reviewNote}</Callout>
              )}

              <div>
                <p className="mb-1 border-b border-line pb-1.5 text-xs font-bold text-accent-ink">Sections</p>
                <Checklist>{gate.map((c) => <CheckRow key={c.title} state={c.state} title={c.title} detail={c.detail}
                  right={{ pass: "Complete", warn: "Needs update", fail: "Exception", todo: "Not yet" }[c.state]} />)}</Checklist>
              </div>

              {selected.canEdit && !selected.reviewerId && (
                <label className="flex items-center gap-2 text-xs text-muted">Reviewer:
                  <select defaultValue="" aria-label="Choose reviewer" onChange={(e) => e.target.value && void run("reviewer", () => updateWorkpaper(selected.id, { reviewer_id: e.target.value }))}
                    className="rounded-lg border border-line bg-panel px-2 py-1 text-xs text-ink outline-none">
                    <option value="">Choose…</option>
                    {reviewers.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                  </select>
                </label>
              )}

              <div>
                <p className="mb-1.5 border-b border-line pb-1.5 text-xs font-bold text-accent-ink">Evidence ({selected.items?.length ?? 0})</p>
                {selected.items?.length ? (
                  <ul className="divide-y divide-line rounded-lg border border-line">
                    {selected.items.map((item) => (
                      <li key={item.id} className="flex items-center justify-between gap-2 px-3 py-2 text-sm">
                        <span className="flex min-w-0 items-center gap-2">
                          <Link2 size={13} className="shrink-0 text-muted" />
                          <span className="min-w-0">
                            <span className={`block truncate text-xs font-semibold ${item.missing ? "italic text-muted" : "text-ink"}`}>{item.title}</span>
                            <span className="text-[11px] text-muted">{KIND_LABEL[item.kind]}{item.missing ? " · deleted" : ""}</span>
                          </span>
                        </span>
                        {selected.canEdit && (
                          <button onClick={() => void run("remove", () => removeWorkpaperItem(selected.id, item.id))} aria-label={`Remove ${item.title}`}
                            className="rounded p-1 text-muted hover:text-bad"><Trash2 size={13} /></button>
                        )}
                      </li>
                    ))}
                  </ul>
                ) : <p className="text-xs text-muted">Nothing attached yet.</p>}
                {selected.canEdit && (
                  <div className="mt-2 flex gap-2">
                    <select value={pick} onChange={(e) => setPick(e.target.value)} aria-label="Item to attach" className={`${inputClass} min-w-0 flex-1 text-xs`}>
                      <option value="">Attach one of your answers, drafts or documents…</option>
                      {available.map((o) => <option key={`${o.kind}:${o.id}`} value={`${o.kind}:${o.id}`}>{KIND_LABEL[o.kind]}: {o.title.slice(0, 80)}</option>)}
                    </select>
                    <Btn disabled={!pick || !!busy} onClick={() => {
                      const [kind, ...rest] = pick.split(":");
                      void run("attach", () => addWorkpaperItem(selected.id, kind as WorkpaperItemKind, rest.join(":"))).then(() => setPick(""));
                    }}>Attach</Btn>
                  </div>
                )}
              </div>

              <div>
                <p className="mb-1.5 border-b border-line pb-1.5 text-xs font-bold text-accent-ink">Preparer notes</p>
                {selected.canEdit ? (
                  <>
                    <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={4} aria-label="Workpaper notes" className={`${inputClass} resize-y`} />
                    <Btn className="mt-1" onClick={() => void run("notes", () => updateWorkpaper(selected.id, { notes }))} disabled={!!busy || notes === (selected.notes ?? "")}>
                      {busy === "notes" ? "Saving…" : "Save notes"}
                    </Btn>
                  </>
                ) : (
                  <p className="whitespace-pre-wrap text-xs text-ink">{selected.notes || <span className="text-muted">No notes.</span>}</p>
                )}
              </div>

              {selected.canReview && (
                <div className="rounded-lg border border-accent/40 bg-accent/5 p-3">
                  <p className="mb-1 text-xs font-bold text-ink">Your review</p>
                  <textarea value={reviewNote} onChange={(e) => setReviewNote(e.target.value)} rows={2} aria-label="Review note"
                    placeholder="Note (required to return)" className={`${inputClass} resize-y`} />
                  <div className="mt-2 grid grid-cols-2 gap-2">
                    <Btn variant="success" onClick={() => void run("signoff", () => reviewWorkpaper(selected.id, "sign_off", reviewNote))} disabled={!!busy}><CheckCircle2 size={13} /> Sign off</Btn>
                    <Btn onClick={() => void run("return", () => reviewWorkpaper(selected.id, "return", reviewNote))} disabled={!!busy || !reviewNote.trim()}><Undo2 size={13} /> Return to owner</Btn>
                  </div>
                </div>
              )}

              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {selected.canEdit && (
                  <Btn variant="primary" onClick={() => void run("submit", () => submitWorkpaper(selected.id))} disabled={!!busy || !selected.reviewerId}
                    title={selected.reviewerId ? undefined : "Choose a reviewer first"}><Send size={13} /> Submit for review</Btn>
                )}
                <Btn onClick={() => void run("pack", () => downloadWorkpaperPack(selected.id))} disabled={!!busy}>
                  <Download size={13} /> {busy === "pack" ? "Building…" : "Download workpaper pack"}
                </Btn>
              </div>
              {selected.status === "in_review" && !selected.canReview && <p className="text-xs text-muted">Waiting for {selected.reviewerName} to review. It can change again once returned.</p>}
              {actionError && <ErrorNote message={actionError} />}
              <ControlNote><b className="text-ink">Sign-off control:</b> preparer ≠ reviewer. Kriton-generated analysis is a draft aid, not an attestation; the reviewer&apos;s decision is recorded against this workpaper.</ControlNote>
            </Inspector>
          )}
        </div>
      )}

      <InfoCards items={[
        { icon: ClipboardCheck, title: "Calculations & tie-outs", text: "Attach the answers and drafts that hold the calculations, so the reviewer sees the same working the conclusion rests on." },
        { icon: FileText, title: "Evidence & authoritative sources", text: "Each attached answer keeps its sources and audit trail; the workpaper pack downloads them with SHA-256 fingerprints." },
        { icon: ShieldCheck, title: "Independent professional sign-off", text: "Only the assigned reviewer can sign off or return a workpaper, and the decision is recorded in the audit log." },
      ]} />
    </WorkflowPage>
  );
}
