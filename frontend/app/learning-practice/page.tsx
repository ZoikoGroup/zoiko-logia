"use client";

import { FormEvent, useEffect, useState } from "react";
import { Search, Loader2, Clock, Compass, Network } from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { Pill } from "@/components/governance/Pill";
import { PanelHeader, PANEL_CLASS } from "@/components/governance/PanelHeader";
import { ADVISOR } from "@/lib/advisor";
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

export default function LearningPracticePage() {
  const [pathways, setPathways] = useState<SyllabusPathway[]>([]);
  const [topics, setTopics] = useState<TopicMapNode[]>([]);
  const [error, setError] = useState("");

  // Ask Kriton (Learning mode)
  const [query, setQuery] = useState("");
  const [asking, setAsking] = useState(false);
  const [askResult, setAskResult] = useState<AskKritonResponse | null>(null);
  const [askError, setAskError] = useState("");

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
      const response = await askKriton(getAuthToken(), { query, mode: "Learning" });
      setAskResult(response);
    } catch (err) {
      setAskError(err instanceof ApiError ? err.message : "Could not reach the orchestration service.");
    } finally {
      setAsking(false);
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

  return (
    <PageShell
      title="Learning & Practice"
      subtitle="Guided learning content, syllabus pathways, and topic maps for skill development."
      showMetrics={false}
    >
      {error && <p className="text-xs text-bad mb-3">{error}</p>}

      <div className={`${PANEL_CLASS} mb-4`}>
        <PanelHeader icon={Search} tone="info" title="Ask Kriton" subtitle="Learning mode" />
        <div className="flex items-center gap-2 text-xs text-muted mb-3">
          <Pill tone="info">Context: Learning</Pill>
          <Pill>Jurisdiction: US</Pill>
          <Pill>Framework: US GAAP</Pill>
        </div>
        <form onSubmit={handleAsk} className="zl-search-surface flex items-center gap-2 rounded-xl border px-4 py-3 transition-shadow">
          <Search size={16} className="text-brand shrink-0" />
          <input
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
            <p className="text-sm text-ink leading-relaxed">
              {askResult.answer?.output_text ?? askResult.safety.refusal_text ?? "No response composed."}
            </p>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <div className={PANEL_CLASS}>
          <PanelHeader icon={Compass} tone="warn" title="Continue Pathway" />
          <ul className="space-y-3">
            {pathways.map((p) => (
              <li key={p.id} className="border-t border-line pt-3 first:border-t-0 first:pt-0">
                <div className="text-sm font-semibold text-ink">{p.topic}</div>
                <div className="text-xs text-muted mt-0.5">
                  {p.body} — {p.qualification} — {p.module}
                </div>
                <div className="text-xs text-ink mt-1">{p.learning_outcome}</div>
              </li>
            ))}
          </ul>
        </div>

        <div className={PANEL_CLASS}>
          <PanelHeader icon={Network} title="Topic Map" />
          <ul className="space-y-3">
            {topics.map((t) => (
              <li key={t.id} className="border-t border-line pt-3 first:border-t-0 first:pt-0">
                <div className="text-sm font-semibold text-ink">{t.topic}</div>
                <div className="text-xs text-muted mt-0.5">Prerequisites: {t.prerequisites}</div>
                <div className="text-xs text-muted">Standards: {t.standards_summary}</div>
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
          <ul className="space-y-1.5">
            {cpdEntries.map((entry) => (
              <li key={entry.id} className="flex items-center justify-between border-t border-line pt-1.5 first:border-t-0 first:pt-0 text-sm">
                <span className="text-ink font-medium">{entry.topic}</span>
                <span className="text-xs text-muted">
                  {entry.minutes} min · {new Date(entry.logged_at).toLocaleDateString()}
                </span>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-3 text-[11px] text-muted border-t border-line pt-2">
          CPD claims are ZoikoLogia-recorded evidence, not a professional-body-issued certificate.
        </p>
      </div>
    </PageShell>
  );
}
