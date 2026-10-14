"use client";

import { useEffect, useState } from "react";
import { Download, FileText, Loader2, MessageSquareText, PackageCheck, Search } from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { Pill } from "@/components/governance/Pill";
import { PanelHeader, PANEL_CLASS } from "@/components/governance/PanelHeader";
import { getAuthToken, listDrafts, listSavedAnswers } from "@/lib/api";
import { downloadEvidencePack, type EvidencePackKind } from "@/lib/accounting-workflows-api";

type Item = { kind: EvidencePackKind; id: string; title: string; detail: string; at: string };

const CONTENTS = [
  ["answer.md / draft.md", "The question and answer as saved, or the draft text"],
  ["sources.md / sources.json", "The web sources and the excerpts the answer was given"],
  ["review.json", "Review cases on the question and the reviewers' decisions"],
  ["feedback.json", "How users rated the answer"],
  ["audit.json", "The question's audit-ledger events with their chain hashes"],
  ["manifest.json", "Who built the pack and when, and a SHA-256 fingerprint of every file"],
];

export default function EvidencePacksPage() {
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");
  const [done, setDone] = useState("");

  useEffect(() => {
    const token = getAuthToken();
    Promise.all([listSavedAnswers(token), listDrafts(token)])
      .then(([answers, drafts]) => {
        const all: Item[] = [
          ...answers.map((a) => ({ kind: "saved-answer" as const, id: a.id, title: a.query_text, detail: `Saved answer · ${a.risk_level} risk`, at: a.created_at })),
          ...drafts.map((d) => ({ kind: "draft" as const, id: d.id, title: d.title, detail: `Draft · ${d.status}${d.saved_answer_id ? " · from a saved answer" : ""}`, at: d.updated_at })),
        ];
        setItems(all.sort((x, y) => y.at.localeCompare(x.at)));
      })
      .catch(() => setError("Could not load your saved answers and drafts."))
      .finally(() => setLoading(false));
  }, []);

  async function download(item: Item) {
    setBusyId(item.id);
    setActionError("");
    setDone("");
    try {
      await downloadEvidencePack(item.kind, item.id);
      setDone(`Evidence pack for "${item.title.slice(0, 60)}" downloaded.`);
    } catch (err) {
      setActionError((err instanceof Error && err.message) || "Could not build the evidence pack.");
    } finally {
      setBusyId(null);
    }
  }

  const needle = query.trim().toLowerCase();
  const visible = items.filter((i) => !needle || i.title.toLowerCase().includes(needle));

  return (
    <PageShell title="Evidence Packs" subtitle="Download what an answer rested on: its sources, reviews and audit trail, in one file." showMetrics={false}>
      {error && <p className="mb-3 text-sm text-bad" role="alert">{error}</p>}
      <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
        <div className={PANEL_CLASS}>
          <PanelHeader icon={PackageCheck} title="Your answers and drafts" subtitle={loading ? undefined : `${visible.length} of ${items.length}`} />
          <label className="mb-3 flex items-center gap-2 rounded-lg border border-line bg-soft px-2.5 py-1.5">
            <Search size={14} className="text-muted" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search" aria-label="Search answers and drafts"
              className="w-full bg-transparent text-sm text-ink outline-none" />
          </label>
          {actionError && <p className="mb-2 text-xs text-bad" role="alert">{actionError}</p>}
          {done && <p className="mb-2 text-xs text-ok">{done}</p>}
          {loading ? (
            <div className="flex items-center justify-center py-10 text-muted"><Loader2 className="mr-2 animate-spin" size={16} /> Loading…</div>
          ) : visible.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted">{items.length ? "Nothing matches." : "Save an answer or create a draft to build an evidence pack for it."}</p>
          ) : (
            <ul className="divide-y divide-line">
              {visible.map((item) => {
                const Icon = item.kind === "draft" ? FileText : MessageSquareText;
                return (
                  <li key={`${item.kind}:${item.id}`} className="flex items-center justify-between gap-3 py-2.5">
                    <span className="flex min-w-0 items-start gap-2">
                      <Icon size={15} className="mt-0.5 shrink-0 text-brand" />
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium text-ink">{item.title}</span>
                        <span className="block text-[11px] text-muted">{item.detail} · {new Date(item.at).toLocaleDateString()}</span>
                      </span>
                    </span>
                    <button
                      onClick={() => void download(item)}
                      disabled={busyId !== null}
                      aria-label={`Download evidence pack for ${item.title}`}
                      className="flex shrink-0 items-center gap-1 rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-ink hover:bg-soft disabled:opacity-60"
                    >
                      {busyId === item.id ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />} Evidence pack
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className={PANEL_CLASS}>
          <PanelHeader icon={FileText} title="What a pack contains" />
          <ul className="space-y-2">
            {CONTENTS.map(([file, what]) => (
              <li key={file} className="text-xs">
                <Pill>{file}</Pill>
                <p className="mt-1 text-ink">{what}</p>
              </li>
            ))}
          </ul>
          <p className="mt-3 border-t border-line pt-2 text-[11px] text-muted">
            Each download is built fresh from Kriton&apos;s records and recorded in the audit log with the files&apos; fingerprints, so a recipient can check nothing was changed.
          </p>
        </div>
      </div>
    </PageShell>
  );
}
