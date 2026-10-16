"use client";

import { FormEvent, useEffect, useState } from "react";
import { Search, Loader2, Clock, Compass, Network, Download, ExternalLink, MessageSquare, Trash2 } from "lucide-react";
import { AnswerRenderer } from "@/components/AnswerRenderer";
import { uniqueCitations } from "@/lib/unique-citations";
import { deleteCPDEntry } from "@/lib/learning-practice-api";
import { PageShell } from "@/components/governance/PageShell";
import { Pill } from "@/components/governance/Pill";
import { PanelHeader, PANEL_CLASS } from "@/components/governance/PanelHeader";
import { ADVISOR } from "@/lib/advisor";
import { PracticeQuiz } from "@/components/learning/PracticeQuiz";
import {
  askKriton,
  createCPDEntry,
  getAuthToken,
  getCPDSummary,
  listCPDEntries,
  listSyllabusPathways,
  listTopicMapNodes,
  ApiError,
  type AskKritonResponse,
  type CPDEntry,
  type CPDSummary,
  type SyllabusPathway,
  type TopicMapNode,
} from "@/lib/api";

const RISK_TONE: Record<string, "ok" | "info" | "warn" | "bad"> = {
  LOW: "ok",
  MEDIUM: "info",
  HIGH: "warn",
  RESTRICTED: "bad",
};

// The jurisdictions Ask Kriton accepts (as on the main Ask Kriton composer).
// The request has no framework field, so none is offered.
const LEARNING_JURISDICTIONS: [string, string][] = [
  ["", "Any jurisdiction"], ["UK", "UK"], ["US", "US"], ["IFRS", "IFRS"], ["UAE", "UAE"], ["India", "India"], ["EU", "EU"],
];

function prerequisiteList(text: string): string[] {
  return (text || "").split(/[,;]/).map((s) => s.trim()).filter(Boolean);
}

function downloadCpdCsv(entries: CPDEntry[]) {
  const cell = (value: string) => `"${value.replace(/"/g, '""')}"`;
  const rows = entries.map((e) => [new Date(e.logged_at).toISOString().slice(0, 10), cell(e.topic), String(e.minutes)].join(","));
  const blob = new Blob([["Date,Topic,Minutes", ...rows].join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `cpd-log-${new Date().toISOString().slice(0, 10)}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

export default function LearningPracticePage() {
  const [pathways, setPathways] = useState<SyllabusPathway[]>([]);
  const [topics, setTopics] = useState<TopicMapNode[]>([]);
  const [error, setError] = useState("");

  // Ask Kriton (Learning mode)
  const [query, setQuery] = useState("");
  const [asking, setAsking] = useState(false);
  const [askResult, setAskResult] = useState<AskKritonResponse | null>(null);
  const [askError, setAskError] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");
  const [highlightTopic, setHighlightTopic] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // CPD log
  const [cpdEntries, setCpdEntries] = useState<CPDEntry[]>([]);
  const [cpdSummary, setCpdSummary] = useState<CPDSummary | null>(null);
  const [cpdTopic, setCpdTopic] = useState("");
  const [cpdMinutes, setCpdMinutes] = useState("30");
  const [loggingCpd, setLoggingCpd] = useState(false);

  function loadCPD() {
    const token = getAuthToken();
    Promise.all([listCPDEntries(token), getCPDSummary(token)]).then(([entries, summary]) => {
      setCpdEntries(entries);
      setCpdSummary(summary);
    });
  }

  useEffect(() => {
    const token = getAuthToken();
    Promise.all([listSyllabusPathways(token), listTopicMapNodes(token)])
      .then(([p, t]) => {
        setPathways(p);
        setTopics(t);
      })
      .catch(() => setError("Could not load learning content from the server."));
    loadCPD();
  }, []);

  async function handleAsk(e: FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setAsking(true);
    setAskResult(null);
    setAskError("");
    try {
      const response = await askKriton(getAuthToken(), { query, mode: "Learning", ...(jurisdiction ? { jurisdiction } : {}) });
      setAskResult(response);
    } catch (err) {
      setAskError(err instanceof ApiError ? err.message : "Could not reach the orchestration service.");
    } finally {
      setAsking(false);
    }
  }

  // Puts a study question in the Ask box; the learner reviews it and presses Ask.
  function askAbout(text: string) {
    setQuery(text);
    const input = document.getElementById("learning-ask-input");
    input?.scrollIntoView({ behavior: "smooth", block: "center" });
    input?.focus();
  }

  function showTopic(name: string) {
    const node = topics.find((t) => t.topic.toLowerCase() === name.toLowerCase());
    if (!node) {
      askAbout(`Explain ${name}.`);
      return;
    }
    setHighlightTopic(node.id);
    document.getElementById(`topic-${node.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  async function handleDeleteCPD(entry: CPDEntry) {
    if (!window.confirm(`Delete the CPD entry "${entry.topic}" (${entry.minutes} min)?`)) return;
    setDeletingId(entry.id);
    try {
      await deleteCPDEntry(entry.id);
      loadCPD();
    } catch {
      setError("Could not delete this CPD entry.");
    } finally {
      setDeletingId(null);
    }
  }

  async function handleLogCPD(e: FormEvent) {
    e.preventDefault();
    const minutes = parseInt(cpdMinutes, 10);
    if (!cpdTopic.trim() || !minutes || minutes <= 0) return;
    setLoggingCpd(true);
    try {
      await createCPDEntry(getAuthToken(), { topic: cpdTopic, minutes });
      setCpdTopic("");
      setCpdMinutes("30");
      loadCPD();
    } catch {
      setError("Could not log this CPD entry.");
    } finally {
      setLoggingCpd(false);
    }
  }

  const studied = pathways.filter((p) => cpdEntries.some((e) => e.topic === p.topic)).length;
  const minutesBy = (key: (e: CPDEntry) => string) =>
    [...cpdEntries.reduce((m, e) => m.set(key(e), (m.get(key(e)) ?? 0) + e.minutes), new Map<string, number>())]
      .sort((a, b) => b[1] - a[1]);
  const byTopic = minutesBy((e) => e.topic);
  const byMonth = minutesBy((e) => new Date(e.logged_at).toLocaleDateString(undefined, { year: "numeric", month: "short" }));
  const sources = askResult?.answer ? uniqueCitations(askResult.answer.citations ?? []) : [];

  return (
    <PageShell
      title="Learning & Practice"
      subtitle="Guided learning content, syllabus pathways, and topic maps for skill development."
    >
      {error && <p className="text-xs text-bad mb-3">{error}</p>}

      <div className={`${PANEL_CLASS} mb-4`}>
        <PanelHeader icon={Search} tone="info" title="Ask Kriton" subtitle="Learning mode" />
        <div className="flex items-center gap-2 text-xs text-muted mb-3">
          <Pill tone="info">Context: Learning</Pill>
          <label className="flex items-center gap-1.5">
            Jurisdiction:
            <select
              value={jurisdiction}
              onChange={(e) => setJurisdiction(e.target.value)}
              aria-label="Jurisdiction"
              className="rounded-lg border border-line bg-soft px-2 py-1 text-xs text-ink outline-none"
            >
              {LEARNING_JURISDICTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
        </div>
        <form onSubmit={handleAsk} className="zl-search-surface flex items-center gap-2 rounded-xl border px-4 py-3 transition-shadow">
          <Search size={16} className="text-brand shrink-0" />
          <input
            id="learning-ask-input"
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={ADVISOR.chatPlaceholder}
            className="w-full bg-transparent text-sm text-ink placeholder:text-muted outline-none"
          />
          <button
            type="submit"
            disabled={asking || !query.trim()}
            className="shrink-0 rounded-lg bg-brand text-white text-xs font-semibold px-3.5 py-2 disabled:opacity-60 disabled:cursor-not-allowed flex items-center gap-1.5"
          >
            {asking && <Loader2 size={12} className="animate-spin" />}
            Ask
          </button>
        </form>
        {askError && <p className="mt-2 text-xs text-bad">{askError}</p>}
        {askResult && (
          <div className="mt-3 rounded-xl border border-line bg-panel p-3">
            <div className="flex items-center gap-2 mb-1.5">
              <Pill tone={RISK_TONE[askResult.safety.risk_level] ?? "neutral"}>{askResult.safety.risk_level}</Pill>
              <span className="text-[11px] text-muted">Outcome: {askResult.outcome}</span>
            </div>
            {askResult.answer?.text ? (
              <AnswerRenderer
                text={askResult.answer.text}
                visualization={askResult.visualization}
                secondaryVisualizations={askResult.secondary_visualizations}
                calculationResult={askResult.answer.calculation_result}
                verifiedCharts={askResult.answer.verified_charts}
                className="text-sm"
              />
            ) : (
              <p className="text-sm text-ink leading-relaxed">{askResult.safety.refusal_text ?? "No response composed."}</p>
            )}
            {sources.length > 0 && (
              <div className="mt-3 border-t border-line pt-2">
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">Sources</p>
                <ul className="space-y-0.5">
                  {sources.map((s) => (
                    <li key={s.ref_id} className="text-xs">
                      {s.url ? (
                        <a href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-brand hover:underline">
                          <ExternalLink size={11} /> {s.title}
                        </a>
                      ) : (
                        <span className="text-ink">{s.title}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      <PracticeQuiz onLogged={loadCPD} />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <div className={PANEL_CLASS}>
          <PanelHeader icon={Compass} tone="warn" title="Continue Pathway" subtitle={pathways.length ? `${studied} of ${pathways.length} studied` : undefined} />
          {pathways.length > 0 && (
            <div className="mb-3 h-1.5 overflow-hidden rounded-full bg-soft" role="progressbar" aria-label="Pathway progress"
              aria-valuemin={0} aria-valuemax={pathways.length} aria-valuenow={studied}>
              <div className="h-full rounded-full bg-ok" style={{ width: `${(studied / pathways.length) * 100}%` }} />
            </div>
          )}
          <ul className="space-y-3">
            {pathways.map((p) => (
              <li key={p.id} className="border-t border-line pt-3 first:border-t-0 first:pt-0">
                <div className="text-sm font-semibold text-ink">{p.topic}</div>
                <div className="text-xs text-muted mt-0.5">
                  {p.body} — {p.qualification} — {p.module}
                </div>
                <div className="text-xs text-ink mt-1">{p.learning_outcome}</div>
                {/* Progress without a new table: a topic counts as studied
                    once CPD time is logged against it. */}
                <div className="mt-1.5 flex flex-wrap items-center gap-3">
                  <button
                    onClick={() => askAbout(`Explain ${p.topic} for ${p.body} ${p.qualification}: ${p.learning_outcome}`)}
                    className="inline-flex items-center gap-1 text-xs font-semibold text-brand hover:underline"
                  >
                    <MessageSquare size={11} /> Ask Kriton
                  </button>
                  {cpdEntries.some((e) => e.topic === p.topic) ? (
                    <Pill tone="ok">Studied ✓</Pill>
                  ) : (
                    <button
                      onClick={() => {
                        setCpdTopic(p.topic);
                        document.getElementById("cpd-minutes")?.focus();
                      }}
                      className="text-xs font-semibold text-brand hover:underline"
                    >
                      Log study time
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>

        <div className={PANEL_CLASS}>
          <PanelHeader icon={Network} title="Topic Map" />
          <ul className="space-y-3">
            {topics.map((t) => (
              <li
                key={t.id}
                id={`topic-${t.id}`}
                className={`border-t border-line pt-3 first:border-t-0 first:pt-0 rounded-lg ${highlightTopic === t.id ? "bg-brand/5 ring-1 ring-brand/30" : ""}`}
              >
                <div className="text-sm font-semibold text-ink">{t.topic}</div>
                <div className="text-xs text-muted mt-0.5 flex flex-wrap items-center gap-1.5">
                  Learn first:
                  {prerequisiteList(t.prerequisites).length ? (
                    prerequisiteList(t.prerequisites).map((name) => (
                      <button
                        key={name}
                        onClick={() => showTopic(name)}
                        title={topics.some((x) => x.topic.toLowerCase() === name.toLowerCase()) ? "Show this topic" : "Ask Kriton about this"}
                        className="rounded-full border border-line px-2 py-0.5 text-[11px] text-ink hover:border-brand hover:text-brand"
                      >
                        {name}
                      </button>
                    ))
                  ) : (
                    <span>nothing</span>
                  )}
                </div>
                <div className="text-xs text-muted">Standards: {t.standards_summary}</div>
                <button
                  onClick={() => askAbout(`Explain ${t.topic} under ${t.standards_summary || "the relevant standards"}.`)}
                  className="mt-1 inline-flex items-center gap-1 text-xs font-semibold text-brand hover:underline"
                >
                  <MessageSquare size={11} /> Ask Kriton
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className={PANEL_CLASS}>
        <PanelHeader
          icon={Clock}
          tone="ok"
          title="CPD / Progress"
          action={
            cpdSummary && (
              <Pill tone="ok">
                <Clock size={11} className="inline mr-1" />
                {cpdSummary.total_hours}h logged
              </Pill>
            )
          }
        />
        <form onSubmit={handleLogCPD} className="flex flex-wrap items-end gap-3 mb-4">
          <div>
            <label className="block text-[11px] text-muted font-medium mb-1">Topic</label>
            <input
              value={cpdTopic}
              onChange={(e) => setCpdTopic(e.target.value)}
              placeholder="e.g. Revenue Recognition"
              className="rounded-lg border border-line bg-soft px-2.5 py-1.5 text-xs text-ink outline-none focus:border-brand min-w-[200px]"
            />
          </div>
          <div>
            <label className="block text-[11px] text-muted font-medium mb-1">Minutes</label>
            <input
              id="cpd-minutes"
              type="number"
              min={1}
              max={600}
              value={cpdMinutes}
              onChange={(e) => setCpdMinutes(e.target.value)}
              className="rounded-lg border border-line bg-soft px-2.5 py-1.5 text-xs text-ink outline-none focus:border-brand w-24"
            />
          </div>
          <button
            type="submit"
            disabled={loggingCpd || !cpdTopic.trim()}
            className="rounded-lg bg-brand text-white text-xs font-semibold px-4 py-2 hover:bg-brand-2 disabled:opacity-60"
          >
            {loggingCpd ? "Logging…" : "Log CPD time"}
          </button>
        </form>

        {cpdEntries.length === 0 ? (
          <p className="text-sm text-muted">No CPD time logged yet.</p>
        ) : (
          <>
            <ul className="space-y-1.5">
              {cpdEntries.map((entry) => (
                <li key={entry.id} className="flex items-center justify-between gap-2 border-t border-line pt-1.5 first:border-t-0 first:pt-0 text-sm">
                  <span className="text-ink font-medium">{entry.topic}</span>
                  <span className="flex items-center gap-2 text-xs text-muted">
                    {entry.minutes} min · {new Date(entry.logged_at).toLocaleDateString()}
                    <button
                      onClick={() => void handleDeleteCPD(entry)}
                      disabled={deletingId === entry.id}
                      aria-label={`Delete CPD entry ${entry.topic}`}
                      className="rounded p-0.5 text-muted hover:text-bad disabled:opacity-50"
                    >
                      <Trash2 size={12} />
                    </button>
                  </span>
                </li>
              ))}
            </ul>

            <div className="mt-4 grid grid-cols-1 gap-3 border-t border-line pt-3 sm:grid-cols-2">
              {([["By topic", byTopic], ["By month", byMonth]] as const).map(([heading, rows]) => (
                <div key={heading}>
                  <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">{heading}</p>
                  <ul className="space-y-0.5 text-xs">
                    {rows.map(([label, minutes]) => (
                      <li key={label} className="flex justify-between gap-2">
                        <span className="truncate text-ink">{label}</span>
                        <span className="shrink-0 text-muted">{(minutes / 60).toFixed(1)}h</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
            <button
              onClick={() => downloadCpdCsv(cpdEntries)}
              className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-ink hover:bg-soft"
            >
              <Download size={12} /> Download CPD log (CSV)
            </button>
          </>
        )}
        <p className="mt-3 text-[11px] text-muted border-t border-line pt-2">
          CPD claims are ZoikoLogia-recorded evidence, not a professional-body-issued certificate.
        </p>
      </div>
    </PageShell>
  );
}
