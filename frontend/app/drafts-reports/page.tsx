"use client";

import { FormEvent, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Download, ExternalLink, Eye, FileText, ListChecks, Loader2, Pencil, Plus, Search, Trash2 } from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { PanelHeader, PANEL_CLASS } from "@/components/governance/PanelHeader";
import { createDraft, getAuthToken, listDrafts, updateDraft, type Draft } from "@/lib/api";
import { deleteDraft, exportDraft, listDraftSources, type DraftExportFormat, type DraftSource } from "@/lib/drafts-api";

const STATUS_OPTIONS = ["Draft", "In Review", "Final"];

const STATUS_TONE: Record<string, "neutral" | "warn" | "ok"> = {
  Draft: "neutral",
  "In Review": "warn",
  Final: "ok",
};

const STATUS_PANEL_TONE: Record<string, "brand" | "warn" | "ok"> = {
  Draft: "brand",
  "In Review": "warn",
  Final: "ok",
};

const EXPORTS: { format: DraftExportFormat; label: string }[] = [
  { format: "docx", label: "Word" },
  { format: "pdf", label: "PDF" },
  { format: "md", label: "Markdown" },
];

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
  const [mode, setMode] = useState<"edit" | "preview">("edit");
  const [sources, setSources] = useState<DraftSource[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");

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
  const visible = drafts.filter(
    (d) =>
      (statusFilter === "All" || d.status === statusFilter) &&
      (!needle || d.title.toLowerCase().includes(needle) || d.content.toLowerCase().includes(needle)),
  );

  return (
    <PageShell
      title="Drafts & Reports"
      subtitle="In-progress reports and drafts generated from Kriton answers."
    >
      {error && <p className="text-xs text-bad mb-3">{error}</p>}

      <div className={`${PANEL_CLASS} mb-4`}>
        <PanelHeader icon={Plus} tone="warn" title="New draft" />
        <form onSubmit={handleCreate} className="flex items-center gap-3">
          <input
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            placeholder="Draft title, e.g. Client memo: revenue recognition"
            className="flex-1 rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
          />
          <button
            type="submit"
            disabled={creating || !newTitle.trim()}
            className="flex items-center gap-1.5 rounded-lg bg-brand text-white text-xs font-semibold px-4 py-2 hover:bg-brand-2 disabled:opacity-60"
          >
            <Plus size={13} /> {creating ? "Creating…" : "New draft"}
          </button>
        </form>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12 text-muted">
          <Loader2 className="animate-spin mr-2" size={16} /> Loading drafts…
        </div>
      ) : drafts.length === 0 ? (
        <Card>
          <p className="text-sm text-muted py-4 text-center">
            No drafts yet — create one above, or click <span className="font-medium text-ink">Create draft</span> from
            a saved answer.
          </p>
        </Card>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_1.4fr] gap-4">
          <div className={PANEL_CLASS}>
            <PanelHeader icon={ListChecks} title="Drafts" subtitle={visible.length === drafts.length ? `${drafts.length} total` : `${visible.length} of ${drafts.length}`} />
            <div className="mb-3 space-y-2">
              <label className="flex items-center gap-2 rounded-lg border border-line bg-soft px-2.5 py-1.5">
                <Search size={14} className="text-muted" />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search title or text"
                  aria-label="Search drafts"
                  className="w-full bg-transparent text-sm text-ink outline-none"
                />
              </label>
              <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by status">
                {["All", ...STATUS_OPTIONS].map((s) => (
                  <button
                    key={s}
                    onClick={() => setStatusFilter(s)}
                    aria-pressed={statusFilter === s}
                    className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${statusFilter === s ? "border-brand bg-brand/10 text-brand" : "border-line text-muted hover:bg-soft"}`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
            {visible.length === 0 ? (
              <p className="py-4 text-center text-sm text-muted">No drafts match.</p>
            ) : (
              <ul className="space-y-0">
                {visible.map((draft) => (
                  <li key={draft.id} className="border-t border-line first:border-t-0">
                    <button
                      onClick={() => selectDraft(draft)}
                      className={`w-full text-left py-2.5 px-1 hover:bg-soft rounded-lg ${
                        selectedId === draft.id ? "bg-soft" : ""
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-semibold text-ink truncate">{draft.title}</span>
                        <Pill tone={STATUS_TONE[draft.status] ?? "neutral"}>{draft.status}</Pill>
                      </div>
                      <div className="text-[11px] text-muted mt-0.5">
                        Updated {new Date(draft.updated_at).toLocaleString()}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className={PANEL_CLASS}>
            <PanelHeader
              icon={FileText}
              tone={selected ? STATUS_PANEL_TONE[selected.status] ?? "brand" : "brand"}
              title={selected ? selected.title : "Select a draft"}
            />
            {selected ? (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <label className="text-xs text-muted font-medium" htmlFor="draft-status">Status:</label>
                    <select
                      id="draft-status"
                      value={editStatus}
                      onChange={(e) => setEditStatus(e.target.value)}
                      className="rounded-lg border border-line bg-soft px-2.5 py-1.5 text-xs text-ink outline-none"
                    >
                      {STATUS_OPTIONS.map((s) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                  </div>
                  <div className="flex rounded-lg border border-line p-0.5" role="tablist" aria-label="Edit or preview">
                    {([["edit", "Edit", Pencil], ["preview", "Preview", Eye]] as const).map(([value, label, Icon]) => (
                      <button
                        key={value}
                        role="tab"
                        aria-selected={mode === value}
                        onClick={() => setMode(value)}
                        className={`flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium ${mode === value ? "bg-brand/10 text-brand" : "text-muted hover:bg-soft"}`}
                      >
                        <Icon size={12} /> {label}
                      </button>
                    ))}
                  </div>
                </div>

                {mode === "edit" ? (
                  <textarea
                    value={editContent}
                    onChange={(e) => setEditContent(e.target.value)}
                    rows={12}
                    className="w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand resize-y"
                    placeholder="Draft content…"
                  />
                ) : (
                  <div className="min-h-[18rem] rounded-lg border border-line px-4 py-2 text-sm" data-testid="draft-preview">
                    {editContent.trim() ? (
                      <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>{withoutCitationMarkers(editContent)}</ReactMarkdown>
                    ) : (
                      <p className="py-6 text-center text-muted">Nothing to preview yet.</p>
                    )}
                  </div>
                )}

                <div className="rounded-lg border border-line p-3">
                  <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">Sources</p>
                  {sourcesLoading ? (
                    <p className="text-xs text-muted">Loading sources…</p>
                  ) : sources.length ? (
                    <ul className="space-y-1">
                      {sources.map((s) => (
                        <li key={s.url}>
                          <a href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-brand hover:underline">
                            <ExternalLink size={11} /> {s.title}
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
                  <button
                    onClick={handleSave}
                    disabled={saving || !dirty}
                    className="rounded-lg bg-brand text-white text-xs font-semibold px-4 py-2 hover:bg-brand-2 disabled:opacity-60"
                  >
                    {saving ? "Saving…" : dirty ? "Save" : "Saved"}
                  </button>
                  <span className="mx-1 h-5 w-px bg-line" />
                  {EXPORTS.map(({ format, label }) => (
                    <button
                      key={format}
                      onClick={() => void handleExport(format)}
                      disabled={!!busy || !editContent.trim()}
                      className="flex items-center gap-1 rounded-lg border border-line px-3 py-2 text-xs font-semibold text-ink hover:bg-soft disabled:opacity-60"
                    >
                      <Download size={12} /> {busy === format ? "Exporting…" : label}
                    </button>
                  ))}
                  <button
                    onClick={() => void handleDelete()}
                    disabled={!!busy}
                    className="ml-auto flex items-center gap-1 rounded-lg border border-bad/30 px-3 py-2 text-xs font-semibold text-bad hover:bg-bad/5 disabled:opacity-60"
                  >
                    <Trash2 size={12} /> {busy === "delete" ? "Deleting…" : "Delete"}
                  </button>
                </div>
                {actionError && <p className="text-xs text-bad" role="alert">{actionError}</p>}
              </div>
            ) : (
              <p className="text-sm text-muted py-4">Pick a draft from the list to view and edit it.</p>
            )}
          </div>
        </div>
      )}
    </PageShell>
  );
}
