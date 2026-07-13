"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Loader2, Trash2, FileText, History } from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { PanelHeader, PANEL_CLASS } from "@/components/governance/PanelHeader";
import {
  createDraft,
  deleteSavedAnswer,
  getAuthToken,
  listSavedAnswers,
  type SavedAnswer,
} from "@/lib/api";

const RISK_TONE: Record<string, "ok" | "info" | "warn" | "bad"> = {
  LOW: "ok",
  MEDIUM: "info",
  HIGH: "warn",
  RESTRICTED: "bad",
};

export default function SavedAnswersPage() {
  const router = useRouter();
  const [answers, setAnswers] = useState<SavedAnswer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [creatingDraftId, setCreatingDraftId] = useState<string | null>(null);

  function load() {
    listSavedAnswers(getAuthToken())
      .then(setAnswers)
      .catch(() => setError("Could not load saved answers from the server."))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  async function handleDelete(id: string) {
    try {
      await deleteSavedAnswer(getAuthToken(), id);
      setAnswers((prev) => prev.filter((a) => a.id !== id));
    } catch {
      setError("Could not delete this saved answer.");
    }
  }

  async function handleCreateDraft(answer: SavedAnswer) {
    setCreatingDraftId(answer.id);
    try {
      await createDraft(getAuthToken(), {
        title: answer.query_text.slice(0, 80),
        content: answer.answer_text,
        saved_answer_id: answer.id,
      });
      router.push("/drafts-reports");
    } catch {
      setError("Could not create a draft from this answer.");
      setCreatingDraftId(null);
    }
  }

  return (
    <PageShell
      title="Saved Answers"
      subtitle="Answers saved from Ask Kriton for reuse, citation, and review."
      showMetrics={false}
    >
      {error && <p className="text-xs text-bad mb-3">{error}</p>}

      {loading ? (
        <div className="flex items-center justify-center py-12 text-muted">
          <Loader2 className="animate-spin mr-2" size={16} /> Loading saved answers…
        </div>
      ) : answers.length === 0 ? (
        <Card>
          <p className="text-sm text-muted py-4 text-center">
            Nothing saved yet — from Ask Kriton, click <span className="font-medium text-ink">Save answer</span> on
            any composed response to keep it here.
          </p>
        </Card>
      ) : (
        <div className="space-y-4">
          {answers.map((answer) => (
            <div key={answer.id} className={PANEL_CLASS}>
              <PanelHeader
                icon={FileText}
                tone={RISK_TONE[answer.risk_level] ?? "brand"}
                title={answer.query_text}
                subtitle={new Date(answer.created_at).toLocaleString()}
                action={<Pill tone={RISK_TONE[answer.risk_level] ?? "neutral"}>{answer.risk_level}</Pill>}
              />
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  {answer.tags.length > 0 && (
                    <div className="flex items-center gap-2 flex-wrap mb-2">
                      {answer.tags.map((tag) => (
                        <Pill key={tag}>{tag}</Pill>
                      ))}
                    </div>
                  )}
                  <p className="text-sm text-muted whitespace-pre-line">{answer.answer_text}</p>
                  <Link
                    href={`/audit-replay?correlation_id=${encodeURIComponent(answer.query_id)}`}
                    className="mt-2 inline-flex items-center gap-1.5 text-xs text-brand hover:underline"
                  >
                    <History size={12} /> View audit trail
                  </Link>
                </div>
                <div className="flex flex-col gap-2 shrink-0">
                  <button
                    onClick={() => handleCreateDraft(answer)}
                    disabled={creatingDraftId === answer.id}
                    className="flex items-center gap-1.5 rounded-lg border border-line bg-panel px-2.5 py-1.5 text-xs font-medium text-ink hover:bg-soft disabled:opacity-60"
                  >
                    <FileText size={13} /> {creatingDraftId === answer.id ? "Creating…" : "Create draft"}
                  </button>
                  <button
                    onClick={() => handleDelete(answer.id)}
                    className="flex items-center gap-1.5 rounded-lg border border-line bg-panel px-2.5 py-1.5 text-xs font-medium text-bad hover:bg-bad/5"
                  >
                    <Trash2 size={13} /> Remove
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </PageShell>
  );
}
