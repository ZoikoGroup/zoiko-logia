"use client";

import { FormEvent, useEffect, useState } from "react";
import { CheckCircle2, Download, FileText, FolderKanban, Loader2, Plus, Search, Send, Trash2, Undo2 } from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { Pill } from "@/components/governance/Pill";
import { PanelHeader, PANEL_CLASS } from "@/components/governance/PanelHeader";
import { getAuthToken, listDrafts, listEngagements, listKritonAttachments, listSavedAnswers, type Engagement } from "@/lib/api";
import {
  addWorkpaperItem, createWorkpaper, downloadWorkpaperPack, getWorkpaper, listReviewers, listWorkpapers, removeWorkpaperItem,
  reviewWorkpaper, submitWorkpaper, updateWorkpaper, type Reviewer, type Workpaper, type WorkpaperItemKind, type WorkpaperStatus,
} from "@/lib/workpapers-api";

const STATUS: Record<WorkpaperStatus, { label: string; tone: "info" | "warn" | "ok" }> = {
  open: { label: "Open", tone: "info" },
  in_review: { label: "In review", tone: "warn" },
  signed_off: { label: "Signed off", tone: "ok" },
};
const KIND_LABEL: Record<WorkpaperItemKind, string> = { saved_answer: "Saved answer", draft: "Draft", document: "Document" };
type Option = { kind: WorkpaperItemKind; id: string; title: string };

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
  const [statusFilter, setStatusFilter] = useState<"all" | WorkpaperStatus>("all");
  const [form, setForm] = useState({ title: "", period: "", engagement_id: "", reviewer_id: "" });
  const [notes, setNotes] = useState("");
  const [reviewNote, setReviewNote] = useState("");
  const [pick, setPick] = useState("");

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
  const visible = workpapers.filter((w) => (statusFilter === "all" || w.status === statusFilter)
    && (!needle || w.title.toLowerCase().includes(needle) || (w.engagementName ?? "").toLowerCase().includes(needle)));
  const attached = new Set((selected?.items ?? []).map((i) => `${i.kind}:${i.itemId}`));
  const available = options.filter((o) => !attached.has(`${o.kind}:${o.id}`));

  return (
    <PageShell title="Workpapers" subtitle="Client job files: the answers, drafts and documents behind a piece of work, with reviewer sign-off.">
      {error && <p className="mb-3 text-sm text-bad" role="alert">{error}</p>}

      <form onSubmit={handleCreate} className={`${PANEL_CLASS} mb-4`}>
        <PanelHeader icon={Plus} tone="warn" title="New workpaper" />
        <div className="grid gap-2 md:grid-cols-[2fr_1fr_1.5fr_1.5fr_auto]">
          <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Title, e.g. Revenue recognition FY26"
            aria-label="Workpaper title" className="rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand" />
          <input value={form.period} onChange={(e) => setForm({ ...form, period: e.target.value })} placeholder="Period, e.g. FY2026"
            aria-label="Period" className="rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand" />
          <select value={form.engagement_id} onChange={(e) => setForm({ ...form, engagement_id: e.target.value })} aria-label="Client job"
            className="rounded-lg border border-line bg-soft px-2 py-2 text-sm text-ink outline-none">
            <option value="">No client job</option>
            {engagements.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </select>
          <select value={form.reviewer_id} onChange={(e) => setForm({ ...form, reviewer_id: e.target.value })} aria-label="Reviewer"
            className="rounded-lg border border-line bg-soft px-2 py-2 text-sm text-ink outline-none">
            <option value="">Reviewer (choose later)</option>
            {reviewers.map((r) => <option key={r.id} value={r.id}>{r.name} · {r.role}</option>)}
          </select>
          <button type="submit" disabled={!!busy || !form.title.trim()}
            className="flex items-center justify-center gap-1.5 rounded-lg bg-brand px-4 py-2 text-xs font-semibold text-white hover:bg-brand-2 disabled:opacity-60">
            <Plus size={13} /> {busy === "create" ? "Creating…" : "Create"}
          </button>
        </div>
      </form>

      {loading ? (
        <div className="flex items-center justify-center py-12 text-muted"><Loader2 className="mr-2 animate-spin" size={16} /> Loading workpapers…</div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[1fr_1.5fr]">
          <div className={PANEL_CLASS}>
            <PanelHeader icon={FolderKanban} title="Workpapers" subtitle={`${visible.length} of ${workpapers.length}`} />
            <label className="mb-2 flex items-center gap-2 rounded-lg border border-line bg-soft px-2.5 py-1.5">
              <Search size={14} className="text-muted" />
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search title or client job" aria-label="Search workpapers"
                className="w-full bg-transparent text-sm text-ink outline-none" />
            </label>
            <div className="mb-3 flex flex-wrap gap-1.5" role="group" aria-label="Filter by status">
              {(["all", "open", "in_review", "signed_off"] as const).map((s) => (
                <button key={s} onClick={() => setStatusFilter(s)} aria-pressed={statusFilter === s}
                  className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${statusFilter === s ? "border-brand bg-brand/10 text-brand" : "border-line text-muted hover:bg-soft"}`}>
                  {s === "all" ? "All" : STATUS[s].label}
                </button>
              ))}
            </div>
            {visible.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted">{workpapers.length ? "No workpapers match." : "No workpapers yet. Create one above."}</p>
            ) : (
              <ul className="divide-y divide-line">
                {visible.map((w) => (
                  <li key={w.id}>
                    <button onClick={() => void open(w.id)} className={`w-full rounded-lg px-1 py-2.5 text-left hover:bg-soft ${selected?.id === w.id ? "bg-soft" : ""}`}>
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-sm font-semibold text-ink">{w.title}</span>
                        <Pill tone={STATUS[w.status].tone}>{STATUS[w.status].label}</Pill>
                      </div>
                      <div className="mt-0.5 text-[11px] text-muted">
                        {[w.engagementName, w.period, `${w.itemCount} item${w.itemCount === 1 ? "" : "s"}`, `owner ${w.ownerName ?? "—"}`].filter(Boolean).join(" · ")}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className={PANEL_CLASS}>
            <PanelHeader icon={FileText} title={selected ? selected.title : "Select a workpaper"} />
            {!selected ? (
              <p className="py-4 text-sm text-muted">Pick a workpaper to see its items and review status.</p>
            ) : (
              <div className="space-y-4">
                <dl className="grid gap-2 text-xs sm:grid-cols-2">
                  <div><dt className="text-muted">Status</dt><dd className="mt-0.5"><Pill tone={STATUS[selected.status].tone}>{STATUS[selected.status].label}</Pill></dd></div>
                  <div><dt className="text-muted">Client job</dt><dd className="mt-0.5 text-ink">{selected.engagementName ?? "None"}</dd></div>
                  <div><dt className="text-muted">Owner</dt><dd className="mt-0.5 text-ink">{selected.ownerName}</dd></div>
                  <div><dt className="text-muted">Reviewer</dt><dd className="mt-0.5 text-ink">{selected.reviewerName ?? "Not chosen"}</dd></div>
                  {selected.signedOffAt && (
                    <div className="sm:col-span-2"><dt className="text-muted">Signed off</dt>
                      <dd className="mt-0.5 text-ok">{selected.signedOffBy} on {new Date(selected.signedOffAt).toLocaleString()}</dd></div>
                  )}
                </dl>

                {selected.reviewNote && selected.status !== "in_review" && (
                  <p className={`rounded-lg border px-3 py-2 text-xs ${selected.status === "signed_off" ? "border-ok/30 bg-ok/5 text-ink" : "border-warn/30 bg-warn/10 text-warn"}`}>
                    Reviewer note: {selected.reviewNote}
                  </p>
                )}

                {selected.canEdit && !selected.reviewerId && (
                  <label className="flex items-center gap-2 text-xs text-muted">Reviewer:
                    <select defaultValue="" aria-label="Choose reviewer" onChange={(e) => e.target.value && void run("reviewer", () => updateWorkpaper(selected.id, { reviewer_id: e.target.value }))}
                      className="rounded-lg border border-line bg-soft px-2 py-1 text-xs text-ink outline-none">
                      <option value="">Choose…</option>
                      {reviewers.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                    </select>
                  </label>
                )}

                <div>
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Notes</p>
                  {selected.canEdit ? (
                    <>
                      <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={4} aria-label="Workpaper notes"
                        className="w-full resize-y rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand" />
                      <button onClick={() => void run("notes", () => updateWorkpaper(selected.id, { notes }))} disabled={!!busy || notes === (selected.notes ?? "")}
                        className="mt-1 rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-ink hover:bg-soft disabled:opacity-60">
                        {busy === "notes" ? "Saving…" : "Save notes"}
                      </button>
                    </>
                  ) : (
                    <p className="whitespace-pre-wrap text-sm text-ink">{selected.notes || <span className="text-muted">No notes.</span>}</p>
                  )}
                </div>

                <div>
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Items ({selected.items?.length ?? 0})</p>
                  {selected.items?.length ? (
                    <ul className="divide-y divide-line rounded-lg border border-line">
                      {selected.items.map((item) => (
                        <li key={item.id} className="flex items-center justify-between gap-2 px-3 py-2 text-sm">
                          <span className="min-w-0">
                            <span className={`block truncate ${item.missing ? "text-muted italic" : "text-ink"}`}>{item.title}</span>
                            <span className="text-[11px] text-muted">{KIND_LABEL[item.kind]}</span>
                          </span>
                          {selected.canEdit && (
                            <button onClick={() => void run("remove", () => removeWorkpaperItem(selected.id, item.id))} aria-label={`Remove ${item.title}`}
                              className="rounded p-1 text-muted hover:text-bad"><Trash2 size={13} /></button>
                          )}
                        </li>
                      ))}
                    </ul>
                  ) : <p className="text-sm text-muted">Nothing attached yet.</p>}
                  {selected.canEdit && (
                    <div className="mt-2 flex gap-2">
                      <select value={pick} onChange={(e) => setPick(e.target.value)} aria-label="Item to attach"
                        className="min-w-0 flex-1 rounded-lg border border-line bg-soft px-2 py-1.5 text-xs text-ink outline-none">
                        <option value="">Attach one of your answers, drafts or documents…</option>
                        {available.map((o) => <option key={`${o.kind}:${o.id}`} value={`${o.kind}:${o.id}`}>{KIND_LABEL[o.kind]}: {o.title.slice(0, 80)}</option>)}
                      </select>
                      <button disabled={!pick || !!busy} onClick={() => {
                        const [kind, ...rest] = pick.split(":");
                        void run("attach", () => addWorkpaperItem(selected.id, kind as WorkpaperItemKind, rest.join(":"))).then(() => setPick(""));
                      }} className="rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-ink hover:bg-soft disabled:opacity-60">Attach</button>
                    </div>
                  )}
                </div>

                {selected.canReview && (
                  <div className="rounded-lg border border-warn/30 bg-warn/5 p-3">
                    <p className="mb-1 text-xs font-semibold text-ink">Your review</p>
                    <textarea value={reviewNote} onChange={(e) => setReviewNote(e.target.value)} rows={2} aria-label="Review note"
                      placeholder="Note (required to return)" className="w-full resize-y rounded-lg border border-line bg-panel px-3 py-2 text-sm text-ink outline-none focus:border-brand" />
                    <div className="mt-2 flex gap-2">
                      <button onClick={() => void run("signoff", () => reviewWorkpaper(selected.id, "sign_off", reviewNote))} disabled={!!busy}
                        className="flex items-center gap-1 rounded-lg bg-ok px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-60"><CheckCircle2 size={13} /> Sign off</button>
                      <button onClick={() => void run("return", () => reviewWorkpaper(selected.id, "return", reviewNote))} disabled={!!busy || !reviewNote.trim()}
                        className="flex items-center gap-1 rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-ink hover:bg-soft disabled:opacity-60"><Undo2 size={13} /> Return to owner</button>
                    </div>
                  </div>
                )}

                <div className="flex flex-wrap gap-2 border-t border-line pt-3">
                  {selected.canEdit && (
                    <button onClick={() => void run("submit", () => submitWorkpaper(selected.id))} disabled={!!busy || !selected.reviewerId}
                      title={selected.reviewerId ? undefined : "Choose a reviewer first"}
                      className="flex items-center gap-1 rounded-lg bg-brand px-3 py-1.5 text-xs font-semibold text-white hover:bg-brand-2 disabled:opacity-60">
                      <Send size={13} /> Submit for review
                    </button>
                  )}
                  <button onClick={() => void run("pack", () => downloadWorkpaperPack(selected.id))} disabled={!!busy}
                    className="flex items-center gap-1 rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-ink hover:bg-soft disabled:opacity-60">
                    <Download size={13} /> {busy === "pack" ? "Building…" : "Download workpaper pack"}
                  </button>
                </div>
                {selected.status === "in_review" && !selected.canReview && <p className="text-xs text-muted">Waiting for {selected.reviewerName} to review. It can change again once returned.</p>}
                {actionError && <p className="text-xs text-bad" role="alert">{actionError}</p>}
              </div>
            )}
          </div>
        </div>
      )}
    </PageShell>
  );
}
