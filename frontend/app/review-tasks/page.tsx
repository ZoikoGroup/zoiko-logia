"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, ClipboardCheck, Loader2, MessageSquareWarning, PencilLine, RefreshCw, XCircle } from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { AnswerRenderer } from "@/components/AnswerRenderer";
import { ApiError, getAuthToken, listReviewCases, resolveReviewCase, getReviewEvidence, type ReviewEvidence, type ReviewCase } from "@/lib/api";

type Decision = "approved" | "corrected" | "rejected" | "needs_evidence";
type Filter = "open" | "needs_evidence" | "resolved";

const SOURCE_LABEL: Record<string, string> = {
  escalation: "Escalated by validation",
  user_feedback: "Reported by a user",
};

function when(value: string) {
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** Ask Kriton review queue. Answers the validator escalated and answers users
 * reported land here; a reviewer approves, corrects or rejects each one, and
 * approved or corrected answers become evaluation (gold) cases. */
export default function ReviewTasksPage() {
  const [filter, setFilter] = useState<Filter>("open");
  const [cases, setCases] = useState<ReviewCase[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  const [mode, setMode] = useState<Decision | null>(null);
  const [corrected, setCorrected] = useState("");
  const [keyFacts, setKeyFacts] = useState("");
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [lastResult, setLastResult] = useState("");
  const [category, setCategory] = useState("reasoning");
  const [evidence, setEvidence] = useState<ReviewEvidence[]>([]);
  const [evidenceError, setEvidenceError] = useState("");
  const [evidenceCaseId, setEvidenceCaseId] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedId) return;
    let active = true;
    const token = getAuthToken();
    if (!token) return;
    void getReviewEvidence(token, selectedId).then((items) => {
      if (active) { setEvidence(items); setEvidenceError(""); setEvidenceCaseId(selectedId); }
    }).catch((err) => {
      if (active) { setEvidence([]); setEvidenceError(err instanceof ApiError ? err.message : "Could not load evidence."); setEvidenceCaseId(selectedId); }
    });
    return () => { active = false; };
  }, [selectedId]);

  // State is only set in the promise callbacks, so the effect below can
  // start a load without a synchronous setState (react-hooks rule); callers
  // that want the spinner set loading themselves.
  const load = useCallback((which: Filter) => {
    const token = getAuthToken();
    const request = token
      ? listReviewCases(token, which)
      : Promise.reject(new ApiError(401, "Sign in to see the review queue."));
    return request
      .then((data) => {
        setLoadError("");
        setCases(data.cases);
        setCounts(data.counts);
        setSelectedId((current) => (data.cases.some((c) => c.id === current) ? current : data.cases[0]?.id ?? null));
      })
      .catch((err) => {
        setLoadError(
          err instanceof ApiError && err.status === 403
            ? "Your role cannot see the review queue. Ask an admin for the review permission."
            : err instanceof ApiError ? err.message : "Could not load the review queue.",
        );
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    void load(filter);
  }, [filter, load]);

  function reload(which: Filter) {
    setLoading(true);
    if (which === filter) void load(which);
    else setFilter(which);
  }

  const selected = cases.find((c) => c.id === selectedId) ?? null;

  function choose(decision: Decision) {
    setMode(decision);
    setSubmitError("");
    setCorrected(decision === "corrected" ? selected?.draft_answer ?? "" : "");
  }

  async function submit() {
    if (!selected || !mode) return;
    const token = getAuthToken();
    if (!token) return;
    setSubmitting(true);
    setSubmitError("");
    try {
      const result = await resolveReviewCase(token, selected.id, {
        decision: mode,
        note: note.trim(),
        corrected_answer: mode === "corrected" ? corrected : "",
        category,
        key_facts: keyFacts.split("\n").map((fact) => fact.trim()).filter(Boolean),
      });
      setLastResult(
        result.gold_case_id
          ? "Resolved — added to the evaluation set."
          : mode === "needs_evidence" ? "Evidence requested — case remains in the queue." : "Resolved.",
      );
      setMode(null);
      setCorrected("");
      setKeyFacts("");
      setNote("");
      await load(filter);
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "Could not save the decision.");
    } finally {
      setSubmitting(false);
    }
  }

  const canSubmit =
    !!mode && !submitting && (mode !== "corrected" || corrected.trim().length > 0)
    && (!["rejected", "needs_evidence"].includes(mode) || note.trim().length > 0)
    && (!["approved", "corrected"].includes(mode) || keyFacts.trim().length > 0);

  return (
    <PageShell
      title="Review Tasks"
      subtitle="Ask Kriton answers escalated by validation or reported by users. Approved and corrected answers become evaluation cases."
      showMetrics={false}
    >
      <div className="mb-4 flex flex-wrap items-center gap-2">
        {(["open", "needs_evidence", "resolved"] as Filter[]).map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => reload(value)}
            aria-pressed={filter === value}
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
              filter === value ? "bg-brand text-white" : "bg-soft text-muted hover:text-ink"
            }`}
          >
            {value === "open" ? "Open" : value === "needs_evidence" ? "Needs evidence" : "Resolved"} ({counts[value] ?? 0})
          </button>
        ))}
        <button
          type="button"
          onClick={() => reload(filter)}
          className="ml-auto inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold text-muted hover:bg-soft hover:text-ink"
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      {lastResult && (
        <p className="mb-3 inline-flex items-center gap-1.5 text-xs font-semibold text-ok" role="status">
          <CheckCircle2 size={14} /> {lastResult}
        </p>
      )}

      {loading ? (
        <div className="flex items-center gap-2 py-16 text-sm text-muted"><Loader2 size={16} className="animate-spin" /> Loading the review queue…</div>
      ) : loadError ? (
        <p className="rounded-xl border border-line bg-panel p-4 text-sm text-bad">{loadError}</p>
      ) : cases.length === 0 ? (
        <p className="rounded-xl border border-line bg-panel p-10 text-center text-sm text-muted">
          {filter === "open" ? "Nothing waiting for review." : filter === "needs_evidence" ? "No cases waiting for evidence." : "No resolved cases yet."}
        </p>
      ) : (
        <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
          <ul className="min-w-0 space-y-2" aria-label="Review cases">
            {cases.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => { setSelectedId(item.id); setKeyFacts(""); setNote(""); setCorrected(""); setCategory("reasoning"); setMode(null); setLastResult(""); }}
                  aria-current={item.id === selectedId}
                  className={`w-full rounded-xl border p-3 text-left transition ${
                    item.id === selectedId ? "border-brand bg-brand/5" : "border-line bg-panel hover:border-ink/20"
                  }`}
                >
                  <span className="flex items-center gap-1.5 text-[11px] font-semibold text-muted">
                    {item.source === "user_feedback" ? <MessageSquareWarning size={13} /> : <AlertTriangle size={13} />}
                    {SOURCE_LABEL[item.source] ?? item.source} · {when(item.created_at)}
                  </span>
                  <span className="mt-1 line-clamp-2 block text-sm font-semibold text-ink">{item.question || "(question not recorded)"}</span>
                  {item.reviewer_decision && (
                    <span className="mt-1 block text-[11px] font-semibold capitalize text-muted">{item.reviewer_decision}</span>
                  )}
                </button>
              </li>
            ))}
          </ul>

          {selected && (
            <section className="min-w-0 rounded-xl border border-line bg-panel p-4" aria-label="Selected case">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted">Question</p>
              <p className="mt-1 text-sm font-semibold text-ink">{selected.question || "(question not recorded)"}</p>

              <p className="mt-4 text-[11px] font-semibold uppercase tracking-wide text-muted">Why it is here</p>
              <p className="mt-1 text-sm text-ink">{selected.reason}</p>

              <p className="mt-4 text-[11px] font-semibold uppercase tracking-wide text-muted">Answer under review</p>
              <div className="mt-1 max-h-96 overflow-y-auto rounded-lg border border-line p-3">
                {selected.draft_answer ? (
                  <AnswerRenderer text={selected.draft_answer} />
                ) : (
                  <p className="text-sm italic text-muted">No draft was recorded (case created before drafts were stored). Correct or reject it.</p>
                )}
              </div>

              <p className="mt-4 text-[11px] font-semibold uppercase tracking-wide text-muted">Evidence retrieved</p>
              {evidenceCaseId !== selected.id ? <p className="mt-1 text-sm text-muted">Loading evidence…</p>
                : evidenceError ? <p role="alert" className="mt-1 text-sm text-bad">{evidenceError}</p>
                : evidence.length === 0 ? <p className="mt-1 text-sm text-muted">No registered evidence bundle was recorded for this answer.</p>
                : <div className="mt-2 space-y-2">{evidence.map((item) => (
                  <details key={`${item.bundle_id}-${item.passage_id}`} className="rounded-lg border border-line p-3">
                    <summary className="cursor-pointer text-sm font-semibold text-ink">{item.title} — {item.locator}</summary>
                    <p className="mt-2 text-xs text-muted">Version {item.source_version_id}{item.effective_from ? ` · From ${item.effective_from}` : ""}{item.effective_to ? ` · Until ${item.effective_to}` : ""}</p>
                    {item.url && /^https?:\/\//i.test(item.url) && <a className="mt-1 block text-xs text-brand underline" href={item.url} target="_blank" rel="noopener noreferrer">Open source</a>}
                    {item.content ? <p className="mt-2 whitespace-pre-wrap text-sm text-ink">{item.content}</p>
                      : <p className="mt-2 text-sm text-muted">Evidence withheld: {item.withheld_reason}</p>}
                  </details>
                ))}</div>}

              {selected.status === "resolved" ? (
                <p className="mt-4 text-sm text-muted">
                  <span className="font-semibold capitalize text-ink">{selected.reviewer_decision}</span>
                  {selected.resolved_at ? ` on ${when(selected.resolved_at)}` : ""}
                  {selected.review_note ? ` — ${selected.review_note}` : ""}
                </p>
              ) : (
                <div className="mt-4">
                  <div className="flex flex-wrap gap-2">
                    <button type="button" onClick={() => choose("approved")} disabled={!selected.draft_answer}
                      className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition disabled:opacity-40 ${mode === "approved" ? "bg-ok text-white" : "bg-ok/10 text-ok hover:bg-ok/20"}`}>
                      <CheckCircle2 size={14} /> Approve
                    </button>
                    <button type="button" onClick={() => choose("corrected")}
                      className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition ${mode === "corrected" ? "bg-brand text-white" : "bg-brand/10 text-brand hover:bg-brand/20"}`}>
                      <PencilLine size={14} /> Correct
                    </button>
                    <button type="button" onClick={() => choose("rejected")}
                      className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition ${mode === "rejected" ? "bg-bad text-white" : "bg-bad/10 text-bad hover:bg-bad/20"}`}>
                      <XCircle size={14} /> Reject
                    </button>
                    <button type="button" onClick={() => choose("needs_evidence")}
                      className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${mode === "needs_evidence" ? "bg-brand text-white" : "bg-soft text-ink"}`}>
                      Request better evidence
                    </button>
                  </div>

                  {mode && (
                    <div className="mt-3 space-y-3">
                      {mode === "corrected" && (
                        <label className="block text-xs font-semibold text-ink">
                          Corrected answer
                          <textarea value={corrected} onChange={(e) => setCorrected(e.target.value)} rows={8} maxLength={20000}
                            className="mt-1 w-full resize-y rounded-lg border border-line bg-panel px-2.5 py-2 text-sm font-normal text-ink focus:border-brand focus:outline-none" />
                        </label>
                      )}
                      {["approved", "corrected"].includes(mode) && (
                        <label className="block text-xs font-semibold text-ink">
                          Required key facts a correct answer must state <span className="font-normal text-muted">(one per line, e.g. “£1.6 million”) — these become the evaluation checks</span>
                          <textarea value={keyFacts} onChange={(e) => setKeyFacts(e.target.value)} rows={3}
                            className="mt-1 w-full resize-y rounded-lg border border-line bg-panel px-2.5 py-2 text-sm font-normal text-ink focus:border-brand focus:outline-none" />
                        </label>
                      )}
                      {["approved", "corrected"].includes(mode) && <label className="block text-xs font-semibold text-ink">
                        Evaluation category
                        <select value={category} onChange={(e) => setCategory(e.target.value)} className="mt-1 block rounded-lg border border-line bg-panel px-2 py-1 text-sm">
                          {["retrieval", "citation", "calculation", "jurisdiction", "freshness", "reasoning", "safety", "off_domain", "missing_context", "visualization"].map((value) => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}
                        </select>
                      </label>}
                      <label className="block text-xs font-semibold text-ink">
                        Note {["rejected", "needs_evidence"].includes(mode) ? <span className="font-normal text-muted">(required: explain the decision and evidence needed)</span> : <span className="font-normal text-muted">(optional)</span>}
                        <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} maxLength={4000}
                          className="mt-1 w-full resize-y rounded-lg border border-line bg-panel px-2.5 py-2 text-sm font-normal text-ink focus:border-brand focus:outline-none" />
                      </label>
                      {submitError && <p className="text-xs font-semibold text-bad">{submitError}</p>}
                      <div className="flex justify-end gap-2">
                        <button type="button" onClick={() => setMode(null)} className="rounded-lg px-3 py-1.5 text-xs font-semibold text-muted hover:bg-soft hover:text-ink">Cancel</button>
                        <button type="button" onClick={() => void submit()} disabled={!canSubmit}
                          className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-brand/90 disabled:opacity-50">
                          {submitting ? <Loader2 size={13} className="animate-spin" /> : <ClipboardCheck size={13} />}
                          Save decision
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </section>
          )}
        </div>
      )}
    </PageShell>
  );
}
