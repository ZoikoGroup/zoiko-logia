"use client";

import { FormEvent, useEffect, useState } from "react";
import { Loader2, Plus, FileText, ListChecks } from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { PanelHeader, PANEL_CLASS } from "@/components/governance/PanelHeader";
import { createDraft, getAuthToken, listDrafts, updateDraft, type Draft } from "@/lib/api";

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

  const selected = drafts.find((d) => d.id === selectedId) ?? null;

  return (
    <PageShell
      title="Drafts & Reports"
      subtitle="In-progress reports and drafts generated from Kriton answers."
      showMetrics={false}
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
            <PanelHeader icon={ListChecks} title="Drafts" subtitle={`${drafts.length} total`} />
            <ul className="space-y-0">
              {drafts.map((draft) => (
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
          </div>

          <div className={PANEL_CLASS}>
            <PanelHeader
              icon={FileText}
              tone={selected ? STATUS_PANEL_TONE[selected.status] ?? "brand" : "brand"}
              title={selected ? selected.title : "Select a draft"}
            />
            {selected ? (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <label className="text-xs text-muted font-medium">Status:</label>
                  <select
                    value={editStatus}
                    onChange={(e) => setEditStatus(e.target.value)}
                    className="rounded-lg border border-line bg-soft px-2.5 py-1.5 text-xs text-ink outline-none"
                  >
                    {STATUS_OPTIONS.map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                </div>
                <textarea
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                  rows={12}
                  className="w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand resize-y"
                  placeholder="Draft content…"
                />
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="rounded-lg bg-brand text-white text-xs font-semibold px-4 py-2 hover:bg-brand-2 disabled:opacity-60"
                >
                  {saving ? "Saving…" : "Save"}
                </button>
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
