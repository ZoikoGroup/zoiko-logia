"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  AlignLeft, CalendarRange, CheckCircle2, ClipboardCheck, Download, ExternalLink, FileText, FileWarning, GitBranch, History,
  Link2, PenLine, Plus, Send, ShieldCheck, Sparkles, Trash2, UserCheck,
} from "lucide-react";
import {
  Badge, Btn, Callout, CheckRow, Checklist, ControlNote, DateCell, Empty, ErrorNote, FilterTabs, Hero, HeroButton, InfoCards,
  Inspector, KeyGrid, ListItem, Loading, Panel, Readiness, RegisterHead, RegisterRow, ScopeBar, SearchField, Stack,
  StatCard, StatGrid, SubTabs, WorkflowPage, inputClass, shortId, type CheckState, type Tone,
} from "@/components/workflow-ui/kit";
import { createDraft, getAuthToken, listDrafts, updateDraft, type Draft } from "@/lib/api";
import { deleteDraft, exportDraft, listDraftSources, type DraftExportFormat, type DraftSource } from "@/lib/drafts-api";

const STATUS_OPTIONS = ["Draft", "In Review", "Final"];

const STATUS_TONE: Record<string, Tone> = {
  Draft: "neutral",
  "In Review": "info",
  Final: "ok",
};

const EXPORTS: { format: DraftExportFormat; label: string }[] = [
  { format: "docx", label: "Word" },
  { format: "pdf", label: "PDF" },
  { format: "md", label: "Markdown" },
];

const TEMPLATE = "md:grid-cols-[minmax(0,2.3fr)_minmax(0,1.2fr)_minmax(0,0.9fr)_minmax(0,0.9fr)_minmax(0,0.6fr)]";
const DAY_MS = 24 * 60 * 60 * 1000;

// Readable formatting for the preview (headings, lists, tables) without a
// typography plugin.
const MARKDOWN_COMPONENTS = {
  h1: (props: React.ComponentProps<"h1">) => <h1 className="mt-4 mb-2 text-xl font-bold text-ink" {...props} />,
  h2: (props: React.ComponentProps<"h2">) => <h2 className="mt-4 mb-2 text-lg font-semibold text-ink" {...props} />,
  h3: (props: React.ComponentProps<"h3">) => <h3 className="mt-3 mb-1.5 text-base font-semibold text-ink" {...props} />,
  p: (props: React.ComponentProps<"p">) => <p className="my-2 leading-6 text-ink" {...props} />,
  ul: (props: React.ComponentProps<"ul">) => <ul className="my-2 list-disc space-y-1 pl-5 text-ink" {...props} />,
  ol: (props: React.ComponentProps<"ol">) => <ol className="my-2 list-decimal space-y-1 pl-5 text-ink" {...props} />,
  a: (props: React.ComponentProps<"a">) => <a className="text-brand underline" target="_blank" rel="noreferrer" {...props} />,
  table: (props: React.ComponentProps<"table">) => <div className="my-3 overflow-x-auto"><table className="w-full border-collapse text-sm" {...props} /></div>,
  th: (props: React.ComponentProps<"th">) => <th className="border border-line bg-soft px-2 py-1 text-left font-semibold" {...props} />,
  td: (props: React.ComponentProps<"td">) => <td className="border border-line px-2 py-1" {...props} />,
  code: (props: React.ComponentProps<"code">) => <code className="rounded bg-soft px-1 py-0.5 text-[13px]" {...props} />,
};

// Kriton's inline citation markers ("[REF-7]") index the answer's citation
// list, not the Sources shown here, so the preview (like the exports) leaves
// them out. The editable text keeps them.
function withoutCitationMarkers(text: string): string {
  return text.replace(/\s?\[REF-\d+\]/g, "");
}

function wordCount(text: string): number {
  return text.trim().split(/\s+/).filter(Boolean).length;
}

function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** Readiness checks a draft passes, read from the saved record and its sources. */
function checks(d: Draft, sources: DraftSource[], sourcesLoading: boolean): { title: string; detail: string; state: CheckState }[] {
  const words = wordCount(d.content);
  const list: { title: string; detail: string; state: CheckState }[] = [
    { title: "Content written", detail: words ? `${words} word${words === 1 ? "" : "s"} saved` : "No saved content yet", state: words ? "pass" : "warn" },
  ];
  if (d.saved_answer_id) {
    list.push({
      title: "Sources on record",
      detail: sourcesLoading ? "Loading sources…" : sources.length ? `${sources.length} web source${sources.length === 1 ? "" : "s"} from the saved answer` : "The saved answer has no web sources on record",
      state: sourcesLoading ? "todo" : sources.length ? "pass" : "warn",
    });
  }
  list.push(
    { title: "Moved to review", detail: d.status === "Draft" ? "Still a working draft" : `Status: ${d.status}`, state: d.status === "Draft" ? "todo" : "pass" },
    { title: "Marked Final", detail: d.status === "Final" ? "Ready for release" : "Not yet marked Final", state: d.status === "Final" ? "pass" : "todo" },
  );
  return list;
}

export default function DraftsReportsPage() {
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");
  const [editStatus, setEditStatus] = useState("Draft");
  const [saving, setSaving] = useState(false);

  const [newTitle, setNewTitle] = useState("");
  const [creating, setCreating] = useState(false);

  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("All");
  const [origin, setOrigin] = useState("");
  const [updatedWithin, setUpdatedWithin] = useState("");
  const [contentScope, setContentScope] = useState("");
  const [mode, setMode] = useState<"edit" | "preview">("edit");
  const [sources, setSources] = useState<DraftSource[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");
  const [now] = useState(() => Date.now());
  const titleInput = useRef<HTMLInputElement>(null);

  function load() {
    listDrafts(getAuthToken())
      .then(setDrafts)
      .catch(() => setError("Could not load drafts from the server."))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  function selectDraft(draft: Draft) {
    setSelectedId(draft.id);
    setEditContent(draft.content);
    setEditStatus(draft.status);
    setActionError("");
    setSources([]);
    setSourcesLoading(true);
    listDraftSources(draft.id)
      .then(setSources)
      .catch(() => setSources([]))
      .finally(() => setSourcesLoading(false));
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!newTitle.trim()) return;
    setCreating(true);
    try {
      const draft = await createDraft(getAuthToken(), { title: newTitle });
      setNewTitle("");
      setDrafts((prev) => [draft, ...prev]);
      selectDraft(draft);
    } catch {
      setError("Could not create a new draft.");
    } finally {
      setCreating(false);
    }
  }

  async function handleSave() {
    if (!selectedId) return;
    setSaving(true);
    try {
      const updated = await updateDraft(getAuthToken(), selectedId, {
        content: editContent,
        status: editStatus,
      });
      setDrafts((prev) => prev.map((d) => (d.id === updated.id ? updated : d)));
    } catch {
      setError("Could not save this draft.");
    } finally {
      setSaving(false);
    }
  }

  async function handleExport(format: DraftExportFormat) {
    if (!selected) return;
    setBusy(format);
    setActionError("");
    try {
      // Export reads the saved draft, so unsaved edits are saved first.
      if (dirty) await handleSave();
      await exportDraft(selected.id, format);
    } catch (err) {
      setActionError((err instanceof Error && err.message) || "Export failed.");
    } finally {
      setBusy(null);
    }
  }

  async function handleDelete() {
    if (!selected || !window.confirm(`Delete "${selected.title}"? This cannot be undone.`)) return;
    setBusy("delete");
    setActionError("");
    try {
      await deleteDraft(selected.id);
      setDrafts((prev) => prev.filter((d) => d.id !== selected.id));
      setSelectedId(null);
    } catch (err) {
      setActionError((err instanceof Error && err.message) || "Could not delete this draft.");
    } finally {
      setBusy(null);
    }
  }

  const selected = drafts.find((d) => d.id === selectedId) ?? null;
  const dirty = !!selected && (editContent !== selected.content || editStatus !== selected.status);
  const needle = query.trim().toLowerCase();
  const scoped = drafts.filter(
    (d) =>
      (!origin || (origin === "answer" ? !!d.saved_answer_id : !d.saved_answer_id)) &&
      (!updatedWithin || now - Date.parse(d.updated_at) <= Number(updatedWithin) * DAY_MS) &&
      (!contentScope || (contentScope === "empty" ? !d.content.trim() : !!d.content.trim())),
  );
  const visible = scoped.filter(
    (d) =>
      (statusFilter === "All" || d.status === statusFilter) &&
      (!needle || d.title.toLowerCase().includes(needle) || d.content.toLowerCase().includes(needle)),
  );
  const count = (status: string) => scoped.filter((d) => d.status === status).length;
  const nextActions = [
    ...scoped.filter((d) => d.status === "In Review").map((d) => ({ d, title: "Awaiting a review decision", icon: Send, tone: "info" as const, badge: "In Review" })),
    ...scoped.filter((d) => d.status !== "Final" && !d.content.trim()).map((d) => ({ d, title: "Add content before export", icon: FileWarning, tone: "warn" as const, badge: "Empty" })),
    ...scoped.filter((d) => d.status === "Final" && d.content.trim()).map((d) => ({ d, title: "Final and ready to export", icon: CheckCircle2, tone: "ok" as const, badge: "Final" })),
  ];
  const gate = selected ? checks(selected, sources, sourcesLoading) : [];

  return (
    <WorkflowPage section="Kriton Workspace" title="Drafts & Reports"
      subtitle="Author, validate, review, and release professional deliverables with accountable sign-off.">
      <ScopeBar items={[
        { icon: GitBranch, label: "Origin", value: origin, onChange: setOrigin,
          options: [{ value: "", label: "All origins" }, { value: "answer", label: "From a saved answer" }, { value: "blank", label: "Started blank" }] },
        { icon: CalendarRange, label: "Updated", value: updatedWithin, onChange: setUpdatedWithin,
          options: [{ value: "", label: "Any time" }, { value: "7", label: "Last 7 days" }, { value: "30", label: "Last 30 days" }] },
        { icon: AlignLeft, label: "Content", value: contentScope, onChange: setContentScope,
          options: [{ value: "", label: "Any content" }, { value: "written", label: "Has content" }, { value: "empty", label: "Empty drafts" }] },
      ]} />

      <Hero icon={PenLine} eyebrow="Controlled authoring · Evidence-led reporting" title="From working draft to defensible deliverable."
        subtitle="Keep every document connected to its sources, reviewers, and release history."
        actions={<>
          <HeroButton href="/ask-kriton"><Sparkles size={13} /> Draft with Kriton</HeroButton>
          <HeroButton primary onClick={() => titleInput.current?.focus()}><Plus size={13} /> New document</HeroButton>
        </>} />

      {error && <ErrorNote message={error} />}

      <StatGrid>
        <StatCard icon={PenLine} tone="neutral" value={count("Draft")} label="In preparation" hint="Status: Draft" />
        <StatCard icon={ClipboardCheck} tone="info" value={count("In Review")} label="Awaiting review" hint="Status: In Review" />
        <StatCard icon={Link2} tone="brand" value={scoped.filter((d) => d.saved_answer_id).length} label="From saved answers" hint="Created from a Kriton answer" />
        <StatCard icon={FileWarning} tone="warn" value={scoped.filter((d) => !d.content.trim()).length} label="No content yet" hint="Cannot be exported" />
        <StatCard icon={CheckCircle2} tone="ok" value={count("Final")} label="Final" hint="Marked ready for release" />
      </StatGrid>

      {loading ? <Loading>Loading drafts…</Loading> : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
          <div className="min-w-0 space-y-4">
            <Panel title="Document workspace" subtitle="Professional drafts, workpapers, reports and client deliverables">
              <form onSubmit={handleCreate} className="mb-3 grid gap-2 rounded-lg border border-dashed border-line bg-soft/50 p-2.5 md:grid-cols-[1fr_auto]">
                <input ref={titleInput} value={newTitle} onChange={(e) => setNewTitle(e.target.value)}
                  placeholder="Draft title, e.g. Client memo: revenue recognition" aria-label="Draft title" className={inputClass} />
                <Btn type="submit" variant="primary" disabled={creating || !newTitle.trim()}><Plus size={13} /> {creating ? "Creating…" : "New draft"}</Btn>
              </form>

              <FilterTabs label="Filter by status" active={statusFilter} onChange={setStatusFilter} tabs={[
                { key: "All", label: "All documents", count: scoped.length },
                ...STATUS_OPTIONS.map((s) => ({ key: s, label: s, count: count(s) })),
              ]} />
              <div className="my-3 flex gap-2">
                <SearchField value={query} onChange={setQuery} placeholder="Search title or text" label="Search drafts" />
              </div>

              {drafts.length === 0 ? (
                <Empty icon={FileText} title="No drafts yet">
                  Create one above, or click <span className="font-medium text-ink">Create draft</span> from a saved answer.
                </Empty>
              ) : visible.length === 0 ? (
                <Empty icon={FileText} title="No drafts match">Change the scope, tab or search.</Empty>
              ) : (
                <div className="overflow-hidden rounded-lg border border-line">
                  <RegisterHead template={TEMPLATE} columns={["Document / reference", "Type / origin", "Content", "Workflow", "Updated"]} />
                  {visible.map((d) => {
                    const words = wordCount(d.content);
                    return (
                      <RegisterRow key={d.id} template={TEMPLATE} selected={selectedId === d.id} onClick={() => selectDraft(d)}
                        icon={FileText} tone={d.status === "Final" ? "ok" : !words ? "warn" : "info"}
                        title={d.title} subtitle={`${shortId("RPT", d.id)} · ${d.saved_answer_id ? "from saved answer" : "started blank"}`}
                        cells={[
                          <Stack key="o" main={d.saved_answer_id ? "From saved answer" : "Started blank"}
                            sub={d.saved_answer_id ? shortId("SA", d.saved_answer_id) : "No source answer"} />,
                          <Stack key="c" main={`${words} word${words === 1 ? "" : "s"}`} sub={words ? `${d.content.length} characters` : "Empty"} subTone={words ? "muted" : "warn"} />,
                          <Badge key="s" tone={STATUS_TONE[d.status] ?? "neutral"}>{d.status}</Badge>,
                          <DateCell key="u" iso={d.updated_at} />,
                        ]} />
                    );
                  })}
                </div>
              )}
              <p className="mt-2 text-[11px] text-muted">{visible.length} of {drafts.length} documents shown</p>
            </Panel>

            <Panel title="My next actions">
              {nextActions.length === 0 ? <p className="py-3 text-xs text-muted">Nothing waiting on you.</p> : (
                <ul>{nextActions.slice(0, 6).map(({ d, title, icon, tone, badge }) => (
                  <ListItem key={`${badge}:${d.id}`} icon={icon} tone={tone} title={title}
                    detail={`${d.title} · updated ${shortDate(d.updated_at)}`} badge={<Badge tone={tone}>{badge}</Badge>}
                    onClick={() => selectDraft(d)} />
                ))}</ul>
              )}
            </Panel>
          </div>

          {!selected ? (
            <section className="rounded-xl border border-line bg-panel p-4 shadow-[0_4px_14px_rgba(13,34,64,0.05)]" aria-label="Document inspector">
              <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted">Selected document</p>
              <Empty icon={FileText} title="Select a document">Pick a draft from the list to view and edit it.</Empty>
            </section>
          ) : (
            <Inspector eyebrow={`Selected document · ${shortId("RPT", selected.id)}`} title={selected.title}
              badges={<>
                <Badge tone={STATUS_TONE[selected.status] ?? "neutral"}>{selected.status}</Badge>
                <Badge>{selected.saved_answer_id ? "From saved answer" : "Started blank"}</Badge>
                {dirty && <Badge tone="warn">Unsaved changes</Badge>}
              </>}
              description={selected.saved_answer_id
                ? "Working draft created from a saved Kriton answer. Its sources come from that answer."
                : "Working draft started blank, with no source answer attached."}>
              <KeyGrid items={[
                ["Status", selected.status],
                ["Origin", selected.saved_answer_id ? shortId("SA", selected.saved_answer_id) : "Started blank"],
                ["Created", new Date(selected.created_at).toLocaleString()],
                ["Updated", new Date(selected.updated_at).toLocaleString()],
              ]} />

              <Readiness label="Document readiness" passed={gate.filter((c) => c.state === "pass").length} total={gate.length}
                hint="Readiness is a checklist indicator, not professional approval." />

              {!editContent.trim() ? (
                <Callout tone="warn" title="Export blocked">Add content first: Word, PDF and Markdown exports need text.</Callout>
              ) : dirty ? (
                <Callout tone="info" title="Unsaved changes">Save them, or export: an export saves your edits first.</Callout>
              ) : null}

              <div>
                <p className="mb-1 border-b border-line pb-1.5 text-xs font-bold text-accent-ink">Readiness checks</p>
                <Checklist>{gate.map((c) => <CheckRow key={c.title} state={c.state} title={c.title} detail={c.detail}
                  right={{ pass: "Complete", warn: "Needs attention", fail: "Exception", todo: "Not yet" }[c.state]} />)}</Checklist>
              </div>

              <div className="flex flex-wrap items-end justify-between gap-3">
                <label className="flex items-center gap-2 text-xs font-medium text-muted" htmlFor="draft-status">Status:
                  <select
                    id="draft-status"
                    value={editStatus}
                    onChange={(e) => setEditStatus(e.target.value)}
                    className="rounded-lg border border-line bg-panel px-2.5 py-1.5 text-xs text-ink outline-none focus:border-accent"
                  >
                    {STATUS_OPTIONS.map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                </label>
                <SubTabs label="Edit or preview" active={mode} onChange={setMode}
                  tabs={[{ key: "edit", label: "Edit" }, { key: "preview", label: "Preview" }]} />
              </div>

              {mode === "edit" ? (
                <textarea
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                  rows={12}
                  className={`${inputClass} resize-y`}
                  placeholder="Draft content…"
                />
              ) : (
                <div className="min-h-72 rounded-lg border border-line px-4 py-2 text-sm" data-testid="draft-preview">
                  {editContent.trim() ? (
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>{withoutCitationMarkers(editContent)}</ReactMarkdown>
                  ) : (
                    <p className="py-6 text-center text-muted">Nothing to preview yet.</p>
                  )}
                </div>
              )}

              <div>
                <p className="mb-1.5 border-b border-line pb-1.5 text-xs font-bold text-accent-ink">Sources{sources.length ? ` (${sources.length})` : ""}</p>
                {sourcesLoading ? (
                  <p className="text-xs text-muted">Loading sources…</p>
                ) : sources.length ? (
                  <ul className="divide-y divide-line rounded-lg border border-line">
                    {sources.map((s) => (
                      <li key={s.url} className="px-3 py-2">
                        <a href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-xs font-semibold text-info hover:underline">
                          <ExternalLink size={12} /> {s.title}
                        </a>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-muted">
                    {selected.saved_answer_id ? "The answer this draft came from has no web sources on record." : "Started blank, so no sources are attached."}
                  </p>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <Btn variant="primary" onClick={() => void handleSave()} disabled={saving || !dirty}>
                  {saving ? "Saving…" : dirty ? "Save" : "Saved"}
                </Btn>
                <span aria-hidden className="mx-0.5 h-5 w-px bg-line" />
                {EXPORTS.map(({ format, label }) => (
                  <Btn key={format} onClick={() => void handleExport(format)} disabled={!!busy || !editContent.trim()}>
                    <Download size={13} /> {busy === format ? "Exporting…" : label}
                  </Btn>
                ))}
                <Btn variant="danger" className="ml-auto" onClick={() => void handleDelete()} disabled={!!busy}>
                  <Trash2 size={13} /> {busy === "delete" ? "Deleting…" : "Delete"}
                </Btn>
              </div>
              {actionError && <ErrorNote message={actionError} />}
              <ControlNote><b className="text-ink">Professional control:</b> generated content is never approval. A Kriton draft is a starting point; a person edits it, sets its status and decides when it is released.</ControlNote>
            </Inspector>
          )}
        </div>
      )}

      <InfoCards items={[
        { icon: ShieldCheck, title: "Citation and evidence integrity", text: "A draft's sources come from the saved answer it was created from. The preview and the Word, PDF and Markdown exports leave out Kriton's [REF-n] markers; the editable text keeps them." },
        { icon: UserCheck, title: "Segregation of duties", text: "Kriton never sets a draft's status: moving it to In Review or Final is a choice a person makes and saves." },
        { icon: History, title: "Version and publication ledger", text: "Each draft records when it was created and last updated, and exports always use the saved text. Deleting a draft is permanent and cannot be undone." },
      ]} />
    </WorkflowPage>
  );
}
