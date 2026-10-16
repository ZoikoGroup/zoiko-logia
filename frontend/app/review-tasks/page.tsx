"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle, CheckCircle2, ClipboardCheck, FileSearch, Gauge, Inbox, MessageSquareWarning, PencilLine, RefreshCw,
  ScrollText, ShieldAlert, ShieldCheck, Siren, Users, XCircle,
} from "lucide-react";
import { AnswerRenderer } from "@/components/AnswerRenderer";
import {
  Badge, Btn, Callout, CheckRow, Checklist, ControlNote, DateCell, Empty, ErrorNote, FilterTabs, Hero, HeroButton, InfoCards,
  Inspector, KeyGrid, ListItem, Loading, Panel, Readiness, RegisterHead, RegisterRow, ScopeBar, SearchField, Stack,
  StatCard, StatGrid, WorkflowPage, inputClass, shortId, type CheckState, type Tone,
} from "@/components/workflow-ui/kit";
import { ApiError, getAuthToken, listReviewCases, releaseReviewedAnswer, resolveReviewCase, triageReviewCase, getReviewEvidence, type ReviewEvidence, type ReviewCase } from "@/lib/api";

type Decision = "approved" | "corrected" | "rejected" | "needs_evidence";
type Filter = "open" | "needs_evidence" | "resolved" | "released";

const FILTER_LABEL: Record<Filter, string> = {
  open: "Open", needs_evidence: "Needs evidence", resolved: "Resolved", released: "Released",
};

const SOURCE_LABEL: Record<string, string> = {
  escalation: "Escalated by validation",
  user_feedback: "Reported by a user",
};
const SOURCE_SHORT: Record<string, { main: string; sub: string }> = {
  escalation: { main: "Escalated", sub: "by validation" },
  user_feedback: { main: "User report", sub: "by a user" },
};
const DECISION_LABEL: Record<string, string> = {
  approved: "Approved", corrected: "Corrected", rejected: "Rejected", needs_evidence: "Needs evidence",
};
const TEMPLATE = "md:grid-cols-[minmax(0,2.4fr)_minmax(0,1fr)_minmax(0,0.8fr)_minmax(0,0.7fr)_minmax(0,0.9fr)]";

function when(value: string) {
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function riskOf(c: ReviewCase) {
  return (c.risk_level ?? "").toLowerCase();
}

function riskTone(risk: string): Tone {
  if (risk === "high" || risk === "restricted") return "bad";
  if (risk === "medium") return "warn";
  if (risk === "low") return "ok";
  return "neutral";
}

function RiskBadge({ c }: { c: ReviewCase }) {
  const risk = riskOf(c);
  return <Badge tone={riskTone(risk)}>{risk ? risk.toUpperCase() : "NOT RATED"}</Badge>;
}

function statusOf(c: ReviewCase): { label: string; tone: Tone } {
  if (c.status === "released") return { label: "Released", tone: "ok" };
  if (c.status === "triaged") return { label: "Triaged", tone: "info" };
  if (c.status === "needs_evidence") return { label: "Needs evidence", tone: "warn" };
  if (c.status === "resolved") {
    const decision = c.reviewer_decision ?? "";
    return { label: DECISION_LABEL[decision] ?? "Resolved", tone: decision === "rejected" ? "bad" : "ok" };
  }
  return { label: "Open", tone: "neutral" };
}

const isPriority = (c: ReviewCase) => ["high", "restricted"].includes(riskOf(c)) || c.status === "needs_evidence";

/** Ask Kriton review queue (ZL-ENG-AGT-01 §08.3). Answers the validator
 * escalated and answers users reported land here: a reviewer triages,
 * approves, corrects or rejects each one. An approved or corrected answer is
 * reused by Kriton only after a second reviewer re-tests and releases it. */
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

  const [query, setQuery] = useState("");
  const [riskScope, setRiskScope] = useState("");
  const [sourceScope, setSourceScope] = useState("");

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

  function pick(id: string) {
    setSelectedId(id); setKeyFacts(""); setNote(""); setCorrected(""); setCategory("reasoning"); setMode(null); setLastResult("");
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

  async function stage(action: "triage" | "release") {
    if (!selected) return;
    const token = getAuthToken();
    if (!token) return;
    setSubmitting(true);
    setSubmitError("");
    try {
      if (action === "triage") {
        await triageReviewCase(token, selected.id, note.trim());
        setLastResult("Triaged — ready for expert review.");
      } else {
        await releaseReviewedAnswer(token, selected.id);
        setLastResult("Re-test passed — released. Kriton can now reuse this answer.");
      }
      setNote("");
      await load(filter);
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "Could not update the case.");
    } finally {
      setSubmitting(false);
    }
  }

  const canSubmit =
    !!mode && !submitting && (mode !== "corrected" || corrected.trim().length > 0)
    && (!["rejected", "needs_evidence"].includes(mode) || note.trim().length > 0)
    && (!["approved", "corrected"].includes(mode) || keyFacts.trim().length > 0);

  // Client-side scope and search over the cases the server returned.
  const needle = query.trim().toLowerCase();
  const risks = [...new Set(cases.map(riskOf).filter(Boolean))].sort();
  const visible = cases.filter((c) => (!riskScope || riskOf(c) === riskScope) && (!sourceScope || c.source === sourceScope)
    && (!needle || (c.question ?? "").toLowerCase().includes(needle) || (c.reason ?? "").toLowerCase().includes(needle)));
  const priorities = visible.filter(isPriority)
    .sort((a, b) => Number(b.status === "needs_evidence") - Number(a.status === "needs_evidence") || b.created_at.localeCompare(a.created_at));
  const decisions = visible.filter((c) => c.reviewer_decision && (c.status === "resolved" || c.status === "released"));

  // Decision readiness, read from the selected case and its recorded evidence.
  const evidenceLoaded = !!selected && evidenceCaseId === selected.id;
  const decided = !!selected && (selected.status === "resolved" || selected.status === "released") && !!selected.reviewer_decision;
  const reusable = !!selected && ["approved", "corrected"].includes(selected.reviewer_decision ?? "");
  const gate: { title: string; detail: string; state: CheckState }[] = !selected ? [] : [
    { title: "Draft answer recorded", detail: selected.draft_answer ? "The answer under review is stored" : "No draft was stored with this case", state: selected.draft_answer ? "pass" : "warn" },
    { title: "Registered evidence", detail: !evidenceLoaded ? "Loading evidence…" : evidenceError ? "Evidence could not be loaded" : evidence.length ? `${evidence.length} passage${evidence.length === 1 ? "" : "s"} recorded` : "No registered evidence bundle was recorded",
      state: !evidenceLoaded ? "todo" : evidenceError ? "fail" : evidence.length ? "pass" : "warn" },
    { title: "Triaged", detail: selected.status === "open" ? "Not yet triaged" : "Past triage", state: selected.status === "open" ? "todo" : "pass" },
    { title: "Reviewer decision", detail: decided ? `${DECISION_LABEL[selected.reviewer_decision ?? ""] ?? selected.reviewer_decision}${selected.resolved_at ? ` · ${when(selected.resolved_at)}` : ""}` : selected.status === "needs_evidence" ? "Waiting for better evidence" : "Not yet decided",
      state: decided ? "pass" : selected.status === "needs_evidence" ? "warn" : "todo" },
    ...(selected.reviewer_decision === "rejected" ? [] : [
      { title: "Re-tested & released", detail: selected.status === "released" ? "Released for reuse by Kriton" : "A second reviewer has not released it", state: (selected.status === "released" ? "pass" : "todo") as CheckState },
    ]),
  ];
  const sourceInfo = selected ? SOURCE_SHORT[selected.source] : undefined;

  return (
    <WorkflowPage section="Accounting Workflows" title="Review Tasks" subtitle="Independent professional review, documented findings, and evidence-bound decisions.">
      <ScopeBar items={[
        { icon: Gauge, label: "Risk level", value: riskScope, onChange: setRiskScope,
          options: [{ value: "", label: "All risk levels" }, ...risks.map((r) => ({ value: r, label: r.charAt(0).toUpperCase() + r.slice(1) }))] },
        { icon: Users, label: "Raised by", value: sourceScope, onChange: setSourceScope, tone: "info",
          options: [{ value: "", label: "All sources" }, { value: "escalation", label: SOURCE_LABEL.escalation }, { value: "user_feedback", label: SOURCE_LABEL.user_feedback }] },
      ]} />

      <Hero icon={ClipboardCheck} eyebrow="Reviewer independence · Source authority · Audit traceability" title="Every review. An accountable decision."
        subtitle="Focus on your next action, reconcile the evidence, document findings, and release only when every gate passes."
        actions={<>
          <HeroButton onClick={() => reload(filter)}><RefreshCw size={13} /> Refresh</HeroButton>
          <HeroButton href="/escalation-queue"><Siren size={13} /> Escalation queue</HeroButton>
        </>} />

      <StatGrid>
        <StatCard icon={Inbox} tone="info" value={(counts.open ?? 0) + (counts.triaged ?? 0)} label="Open reviews" hint="Received or triaged" />
        <StatCard icon={ClipboardCheck} tone="neutral" value={counts.triaged ?? 0} label="Triaged" hint="Ready for expert review" />
        <StatCard icon={FileSearch} tone="warn" value={counts.needs_evidence ?? 0} label="Needs evidence" hint="Better evidence requested" />
        <StatCard icon={ShieldAlert} tone="bad" value={counts.resolved ?? 0} label="Resolved — awaiting release" hint="Not reused until re-tested" />
        <StatCard icon={CheckCircle2} tone="ok" value={counts.released ?? 0} label="Released for reuse" hint="Re-tested by a second reviewer" />
      </StatGrid>

      {lastResult && (
        <p className="inline-flex items-center gap-1.5 text-xs font-semibold text-ok" role="status">
          <CheckCircle2 size={14} /> {lastResult}
        </p>
      )}

      {loading ? <Loading>Loading the review queue…</Loading> : loadError ? <ErrorNote message={loadError} /> : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
          <div className="min-w-0 space-y-4">
            <Panel title="Review queue" subtitle="Your decisions and assignments · prioritised by risk">
              <FilterTabs label="Filter review cases" active={filter} onChange={(value) => reload(value)} tabs={(["open", "needs_evidence", "resolved", "released"] as Filter[]).map((value) => ({
                key: value, label: FILTER_LABEL[value], count: value === "open" ? (counts.open ?? 0) + (counts.triaged ?? 0) : counts[value] ?? 0,
              }))} />
              <div className="my-3 flex gap-2">
                <SearchField value={query} onChange={setQuery} placeholder="Search question or reason…" label="Search review cases" />
              </div>

              {cases.length === 0 ? (
                <Empty icon={ClipboardCheck} title={filter === "open" ? "Nothing waiting for review." : filter === "needs_evidence" ? "No cases waiting for evidence." : filter === "released" ? "No released answers yet." : "No resolved cases yet."} />
              ) : visible.length === 0 ? (
                <Empty icon={ClipboardCheck} title="No review cases match">Change the risk level, source or search.</Empty>
              ) : (
                <div className="overflow-hidden rounded-lg border border-line">
                  <RegisterHead template={TEMPLATE} columns={["Review / linked work", "Raised by", "Risk", "Received", "Status"]} />
                  {visible.map((item) => {
                    const status = statusOf(item);
                    const src = SOURCE_SHORT[item.source];
                    return (
                      <RegisterRow key={item.id} template={TEMPLATE} selected={item.id === selectedId} onClick={() => pick(item.id)}
                        icon={item.source === "user_feedback" ? MessageSquareWarning : AlertTriangle} tone={riskTone(riskOf(item)) === "neutral" ? "info" : riskTone(riskOf(item))}
                        title={item.question || "(question not recorded)"} subtitle={[shortId("RT", item.id), item.reason].filter(Boolean).join(" · ")}
                        cells={[
                          <Stack key="s" main={src?.main ?? item.source} sub={src?.sub} />,
                          <RiskBadge key="r" c={item} />,
                          <DateCell key="d" iso={item.created_at} />,
                          <Badge key="st" tone={status.tone}>{status.label}</Badge>,
                        ]} />
                    );
                  })}
                </div>
              )}
              <p className="mt-2 text-[11px] text-muted">{visible.length} of {cases.length} review records shown</p>
            </Panel>

            <div className="grid gap-4 md:grid-cols-2">
              <Panel title="Immediate reviewer priorities">
                {priorities.length === 0 ? <p className="py-3 text-xs text-muted">No high-risk or evidence-blocked cases in this list.</p> : (
                  <ul>{priorities.slice(0, 5).map((c) => (
                    <ListItem key={c.id} icon={c.status === "needs_evidence" ? FileSearch : ShieldAlert} tone={c.status === "needs_evidence" ? "warn" : "bad"}
                      title={c.status === "needs_evidence" ? "Evidence requested" : `${riskOf(c).charAt(0).toUpperCase()}${riskOf(c).slice(1)} risk answer`}
                      detail={`${c.question || "(question not recorded)"} · ${shortId("RT", c.id)} · ${c.reason}`}
                      badge={<RiskBadge c={c} />} onClick={() => pick(c.id)} />
                  ))}</ul>
                )}
              </Panel>
              <Panel title="Review decisions">
                {decisions.length === 0 ? <p className="py-3 text-xs text-muted">No decisions in this list. Switch to Resolved or Released.</p> : (
                  <ul>{decisions.slice(0, 5).map((c) => (
                    <ListItem key={c.id} icon={c.reviewer_decision === "rejected" ? XCircle : CheckCircle2} tone={c.reviewer_decision === "rejected" ? "bad" : "ok"}
                      title={DECISION_LABEL[c.reviewer_decision ?? ""] ?? "Resolved"}
                      detail={`${c.question || "(question not recorded)"}${c.resolved_at ? ` · ${when(c.resolved_at)}` : ""}`}
                      badge={<Badge tone={c.status === "released" ? "ok" : c.reviewer_decision === "rejected" ? "bad" : "warn"}>
                        {c.status === "released" ? "Released" : c.reviewer_decision === "rejected" ? "Closed" : "Awaiting release"}
                      </Badge>}
                      onClick={() => pick(c.id)} />
                  ))}</ul>
                )}
              </Panel>
            </div>
          </div>

          {!selected ? (
            <section className="rounded-xl border border-line bg-panel p-4 shadow-[0_4px_14px_rgba(13,34,64,0.05)]" aria-label="Review inspector">
              <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted">Review inspector</p>
              <Empty icon={ClipboardCheck} title="Select a review case">Pick a case to see the answer, its evidence and the decision options.</Empty>
            </section>
          ) : (
            <Inspector eyebrow={`Review inspector · ${shortId("RT", selected.id)}`} title={selected.question || "(question not recorded)"}
              badges={<>
                <Badge tone={statusOf(selected).tone}>{statusOf(selected).label}</Badge>
                <RiskBadge c={selected} />
                <Badge tone="info">{SOURCE_LABEL[selected.source] ?? selected.source}</Badge>
              </>}
              description={selected.reason ? `Why it is here: ${selected.reason}` : undefined}>
              <KeyGrid items={[
                ["Raised by", sourceInfo ? `${sourceInfo.main} ${sourceInfo.sub}` : selected.source],
                ["Risk level", riskOf(selected) ? riskOf(selected).toUpperCase() : "Not rated"],
                ["Received", when(selected.created_at)],
                ["Decision", selected.reviewer_decision ? DECISION_LABEL[selected.reviewer_decision] ?? selected.reviewer_decision : "Not yet decided"],
                ["Resolved", selected.resolved_at ? when(selected.resolved_at) : "—"],
                ["Linked query", selected.query_id ? shortId("Q", selected.query_id) : "—"],
              ]} />

              <Readiness label="Decision readiness" passed={gate.filter((c) => c.state === "pass").length} total={gate.length}
                hint="Readiness is a checklist indicator, not a review decision." />

              {selected.status === "released" ? (
                <Callout tone="ok" title="Released for reuse">A second reviewer re-tested this answer; Kriton can reuse it.</Callout>
              ) : !selected.draft_answer && !decided ? (
                <Callout tone="warn" title="Approval unavailable — no draft answer was recorded">Correct or reject the case instead.</Callout>
              ) : evidenceLoaded && !evidenceError && evidence.length === 0 && !decided ? (
                <Callout tone="warn" title="Evidence gap">No registered evidence was recorded for this answer. Check the answer against an authoritative source or request better evidence.</Callout>
              ) : selected.status === "needs_evidence" ? (
                <Callout tone="warn" title="Better evidence requested">{selected.review_note || "The case stays in the queue until it is decided."}</Callout>
              ) : null}

              <div>
                <p className="mb-1 border-b border-line pb-1.5 text-xs font-bold text-accent-ink">Review gates</p>
                <Checklist>{gate.map((c) => <CheckRow key={c.title} state={c.state} title={c.title} detail={c.detail}
                  right={{ pass: "Complete", warn: "Needs attention", fail: "Exception", todo: "Not yet" }[c.state]} />)}</Checklist>
              </div>

              <div>
                <p className="mb-1.5 border-b border-line pb-1.5 text-xs font-bold text-accent-ink">Answer under review</p>
                <div className="max-h-96 overflow-y-auto rounded-lg border border-line p-3">
                  {selected.draft_answer ? (
                    <AnswerRenderer text={selected.draft_answer} />
                  ) : (
                    <p className="text-sm italic text-muted">No draft was recorded (case created before drafts were stored). Correct or reject it.</p>
                  )}
                </div>
              </div>

              <div>
                <p className="mb-1.5 border-b border-line pb-1.5 text-xs font-bold text-accent-ink">Evidence retrieved{evidenceLoaded && !evidenceError ? ` (${evidence.length})` : ""}</p>
                {!evidenceLoaded ? <p className="text-xs text-muted">Loading evidence…</p>
                  : evidenceError ? <p role="alert" className="text-xs text-bad">{evidenceError}</p>
                  : evidence.length === 0 ? <p className="text-xs text-muted">No registered evidence bundle was recorded for this answer.</p>
                  : <div className="space-y-2">{evidence.map((item) => (
                    <details key={`${item.bundle_id}-${item.passage_id}`} className="rounded-lg border border-line p-3">
                      <summary className="cursor-pointer text-xs font-semibold text-ink">{item.title} — {item.locator}</summary>
                      <p className="mt-2 text-[11px] text-muted">Version {item.source_version_id}{item.effective_from ? ` · From ${item.effective_from}` : ""}{item.effective_to ? ` · Until ${item.effective_to}` : ""}</p>
                      {item.url && /^https?:\/\//i.test(item.url) && <a className="mt-1 block text-[11px] text-info underline" href={item.url} target="_blank" rel="noopener noreferrer">Open source</a>}
                      {item.content ? <p className="mt-2 whitespace-pre-wrap text-sm text-ink">{item.content}</p>
                        : <p className="mt-2 text-sm text-muted">Evidence withheld: {item.withheld_reason}</p>}
                    </details>
                  ))}</div>}
              </div>

              {selected.status === "resolved" || selected.status === "released" ? (
                <div className="rounded-lg border border-line bg-soft/60 p-3 text-xs text-muted">
                  <p className="mb-1 text-xs font-bold text-ink">Recorded decision</p>
                  <p>
                    <span className="font-semibold text-ink">{DECISION_LABEL[selected.reviewer_decision ?? ""] ?? selected.reviewer_decision}</span>
                    {selected.resolved_at ? ` on ${when(selected.resolved_at)}` : ""}
                    {selected.review_note ? ` — ${selected.review_note}` : ""}
                    {selected.status === "released" ? " · Released for reuse" : ""}
                  </p>
                  {selected.status === "resolved" && reusable && (
                    <div className="mt-3">
                      <p className="text-xs">Not reused by Kriton yet. A different reviewer must re-test and release it.</p>
                      <Btn variant="success" className="mt-2" onClick={() => void stage("release")} busy={submitting}>
                        {!submitting && <CheckCircle2 size={13} />} Re-test &amp; release
                      </Btn>
                      {submitError && <div className="mt-2"><ErrorNote message={submitError} /></div>}
                    </div>
                  )}
                </div>
              ) : (
                <div className="rounded-lg border border-accent/40 bg-accent/5 p-3">
                  <p className="mb-2 text-xs font-bold text-ink">Your decision</p>
                  <div className="flex flex-wrap gap-2">
                    {selected.status === "open" && (
                      <Btn onClick={() => void stage("triage")} disabled={submitting}><ClipboardCheck size={13} /> Triage</Btn>
                    )}
                    <Btn variant={mode === "approved" ? "success" : "secondary"} onClick={() => choose("approved")} disabled={!selected.draft_answer}>
                      <CheckCircle2 size={13} /> Approve
                    </Btn>
                    <Btn variant={mode === "corrected" ? "primary" : "secondary"} onClick={() => choose("corrected")}>
                      <PencilLine size={13} /> Correct
                    </Btn>
                    <Btn variant="danger" className={mode === "rejected" ? "ring-2 ring-bad/40" : ""} onClick={() => choose("rejected")}>
                      <XCircle size={13} /> Reject
                    </Btn>
                    <Btn variant={mode === "needs_evidence" ? "primary" : "secondary"} onClick={() => choose("needs_evidence")}>
                      Request better evidence
                    </Btn>
                  </div>

                  {mode && (
                    <div className="mt-3 space-y-3">
                      {mode === "corrected" && (
                        <label className="block text-xs font-semibold text-ink">
                          Corrected answer
                          <textarea value={corrected} onChange={(e) => setCorrected(e.target.value)} rows={8} maxLength={20000}
                            className={`${inputClass} mt-1 resize-y font-normal`} />
                        </label>
                      )}
                      {["approved", "corrected"].includes(mode) && (
                        <label className="block text-xs font-semibold text-ink">
                          Required key facts a correct answer must state <span className="font-normal text-muted">(one per line, e.g. “£1.6 million”) — these become the evaluation checks</span>
                          <textarea value={keyFacts} onChange={(e) => setKeyFacts(e.target.value)} rows={3}
                            className={`${inputClass} mt-1 resize-y font-normal`} />
                        </label>
                      )}
                      {["approved", "corrected"].includes(mode) && <label className="block text-xs font-semibold text-ink">
                        Evaluation category
                        <select value={category} onChange={(e) => setCategory(e.target.value)} className={`${inputClass} mt-1 font-normal`}>
                          {["retrieval", "citation", "calculation", "jurisdiction", "freshness", "reasoning", "safety", "off_domain", "missing_context", "visualization"].map((value) => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}
                        </select>
                      </label>}
                      <label className="block text-xs font-semibold text-ink">
                        Note {["rejected", "needs_evidence"].includes(mode) ? <span className="font-normal text-muted">(required: explain the decision and evidence needed)</span> : <span className="font-normal text-muted">(optional)</span>}
                        <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} maxLength={4000}
                          className={`${inputClass} mt-1 resize-y font-normal`} />
                      </label>
                      {submitError && <ErrorNote message={submitError} />}
                      <div className="flex justify-end gap-2">
                        <Btn variant="quiet" onClick={() => setMode(null)}>Cancel</Btn>
                        <Btn variant="primary" onClick={() => void submit()} disabled={!canSubmit} busy={submitting}>
                          {!submitting && <ClipboardCheck size={13} />} Save decision
                        </Btn>
                      </div>
                    </div>
                  )}
                  {!mode && submitError && <div className="mt-2"><ErrorNote message={submitError} /></div>}
                </div>
              )}

              <ControlNote><b className="text-ink">Review control:</b> reviewer ≠ preparer — Kriton drafts the answer and cannot approve its own answers; approved answers are reused only after a second reviewer re-tests and releases them.</ControlNote>
            </Inspector>
          )}
        </div>
      )}

      <InfoCards items={[
        { icon: ShieldCheck, title: "Independent reviewer authorization", text: "Only roles with the review permission can open this queue, and a different reviewer must re-test an approved answer before Kriton reuses it." },
        { icon: FileSearch, title: "Source & evidence integrity", text: "Each case shows the registered evidence passages recorded for the answer, with source version and effective dates; withheld passages state why." },
        { icon: ScrollText, title: "Review decision audit ledger", text: "Each decision is stored on the case with its note and time; approved and corrected answers carry key facts that become evaluation checks." },
      ]} />
    </WorkflowPage>
  );
}
