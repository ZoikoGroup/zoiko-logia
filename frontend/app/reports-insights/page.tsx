"use client";

import { useEffect, useState } from "react";
import { BarChart3, Clock3, Loader2, MessageSquare, ShieldCheck, ThumbsDown, ThumbsUp } from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { PanelHeader, PANEL_CLASS } from "@/components/governance/PanelHeader";
import { getInsights, type Count, type Insights } from "@/lib/insights-api";

const WINDOWS = [7, 30, 90];

const SECTION_NAMES: Record<string, string> = {
  questionsPerDay: "questions per day", outcomes: "outcomes", routes: "routes", riskLevels: "risk levels",
  latency: "response time", answers: "topics and sources", reviews: "review cases", feedback: "feedback",
  workspace: "workspace output",
};

const pretty = (label: string) => label.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

/** Every day in the window, with zero for days without questions, so gaps read as gaps. */
function fillDays(points: { date: string; count: number }[], since: string, days: number) {
  const counts = new Map(points.map((p) => [p.date.slice(0, 10), p.count]));
  const start = new Date(since);
  return Array.from({ length: days }, (_, i) => {
    const d = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth(), start.getUTCDate() + i + 1));
    const key = d.toISOString().slice(0, 10);
    return { date: key, count: counts.get(key) ?? 0 };
  });
}

function StatTile({ icon: Icon, label, value, detail }: { icon: typeof Clock3; label: string; value: string; detail?: string }) {
  return (
    <div className="rounded-2xl border border-line bg-panel p-4">
      <p className="flex items-center gap-1.5 text-xs font-medium text-muted"><Icon size={14} className="text-brand" /> {label}</p>
      <p className="mt-2 text-2xl font-semibold tracking-tight text-ink">{value}</p>
      {detail && <p className="mt-0.5 text-xs text-muted">{detail}</p>}
    </div>
  );
}

/** Questions per day: one series, one hue, with a hover readout and a table view. */
function DailyChart({ days }: { days: { date: string; count: number }[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const [asTable, setAsTable] = useState(false);
  const max = Math.max(1, ...days.map((d) => d.count));
  const label = (date: string) => new Date(`${date}T00:00:00Z`).toLocaleDateString(undefined, { day: "numeric", month: "short", timeZone: "UTC" });
  const shown = hover !== null ? days[hover] : null;
  return (
    <div>
      <div className="mb-2 flex items-center justify-between text-xs text-muted">
        <span aria-live="polite">{shown ? `${label(shown.date)}: ${shown.count} question${shown.count === 1 ? "" : "s"}` : `Peak ${max} a day`}</span>
        <button onClick={() => setAsTable((v) => !v)} className="font-semibold text-brand hover:underline">{asTable ? "Show chart" : "Show table"}</button>
      </div>
      {asTable ? (
        <div className="max-h-64 overflow-y-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-muted"><th className="pb-1 font-medium">Date</th><th className="pb-1 text-right font-medium">Questions</th></tr></thead>
            <tbody>{days.map((d) => <tr key={d.date} className="border-t border-line"><td className="py-1 text-ink">{label(d.date)}</td><td className="py-1 text-right tabular-nums text-ink">{d.count}</td></tr>)}</tbody>
          </table>
        </div>
      ) : (
        <>
          <div className="flex h-40 items-end gap-[2px] border-b border-line" role="img" aria-label="Questions asked per day" onMouseLeave={() => setHover(null)}>
            {days.map((d, i) => (
              <div key={d.date} className="flex h-full flex-1 items-end" onMouseEnter={() => setHover(i)} title={`${label(d.date)}: ${d.count}`}>
                <div
                  className={`w-full rounded-t-[4px] ${hover === i ? "bg-brand-2" : "bg-brand"}`}
                  style={{ height: d.count ? `${Math.max(2, (d.count / max) * 100)}%` : 0 }}
                />
              </div>
            ))}
          </div>
          <div className="mt-1 flex justify-between text-[11px] text-muted"><span>{label(days[0].date)}</span><span>{label(days[days.length - 1].date)}</span></div>
        </>
      )}
    </div>
  );
}

/** A ranked list with a proportional bar; the number is always written out. */
function RankedBars({ rows, empty }: { rows: Count[]; empty: string }) {
  if (!rows.length) return <p className="py-3 text-sm text-muted">{empty}</p>;
  const max = Math.max(...rows.map((r) => r.count));
  const total = rows.reduce((s, r) => s + r.count, 0);
  return (
    <ul className="space-y-2">
      {rows.map((r) => (
        <li key={r.label} title={`${pretty(r.label)}: ${r.count} (${Math.round((r.count / total) * 100)}%)`}>
          <div className="flex justify-between gap-2 text-xs">
            <span className="truncate text-ink">{pretty(r.label)}</span>
            <span className="shrink-0 tabular-nums text-muted">{r.count} · {Math.round((r.count / total) * 100)}%</span>
          </div>
          <div className="mt-1 h-1.5 rounded-full bg-soft">
            <div className="h-full rounded-full bg-brand" style={{ width: `${(r.count / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

function Panel({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className={PANEL_CLASS}>
      <PanelHeader icon={BarChart3} title={title} subtitle={subtitle} />
      {children}
    </div>
  );
}

const unavailable = <p className="py-3 text-sm text-muted">Not available right now.</p>;

export default function ReportsInsightsPage() {
  const [windowDays, setWindowDays] = useState(30);
  const [data, setData] = useState<Insights | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    getInsights(windowDays, controller.signal)
      .then((result) => { setData(result); setError(""); })
      .catch((err) => { if (err?.name !== "AbortError") setError("Could not load insights from the server."); })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [windowDays]);

  function chooseWindow(days: number) {
    setLoading(true);
    setWindowDays(days);
  }

  const finalised = (data?.outcomes ?? []).reduce((s, r) => s + r.count, 0);
  const answered = data?.outcomes?.find((r) => r.label === "answered")?.count ?? 0;
  const up = data?.feedback?.up ?? 0;
  const down = data?.feedback?.down ?? 0;
  const openReviews = (data?.reviews?.byStatus.open ?? 0) + (data?.reviews?.byStatus.needs_evidence ?? 0);

  return (
    <PageShell title="Reports & Insights" subtitle="How Kriton is used in your workspace, from its own records." showMetrics={false}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex rounded-lg border border-line p-0.5" role="group" aria-label="Time range">
          {WINDOWS.map((d) => (
            <button
              key={d}
              onClick={() => chooseWindow(d)}
              aria-pressed={windowDays === d}
              className={`rounded-md px-3 py-1 text-xs font-medium ${windowDays === d ? "bg-brand/10 text-brand" : "text-muted hover:bg-soft"}`}
            >
              Last {d} days
            </button>
          ))}
        </div>
        {data && <span className="text-xs text-muted">Updated {new Date(data.generatedAt).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}</span>}
      </div>

      {error && <p className="mb-3 text-sm text-bad" role="alert">{error}</p>}
      {data && data.unavailable.length > 0 && (
        <p className="mb-3 rounded-xl border border-warn/30 bg-warn/10 px-4 py-2 text-xs text-warn">
          Some sections could not be read in time: {data.unavailable.map((s) => SECTION_NAMES[s] ?? s).join(", ")}.
        </p>
      )}

      {loading && !data ? (
        <div className="flex items-center justify-center py-16 text-muted"><Loader2 className="mr-2 animate-spin" size={16} /> Loading insights…</div>
      ) : data && (
        <div className={`space-y-4 ${loading ? "opacity-60" : ""}`}>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            <StatTile icon={MessageSquare} label="Questions asked" value={data.totalQuestions === null ? "—" : String(data.totalQuestions)} detail={`Last ${data.windowDays} days`} />
            <StatTile icon={ShieldCheck} label="Answered" value={finalised ? `${Math.round((answered / finalised) * 100)}%` : "—"} detail={finalised ? `${answered} of ${finalised} responses` : "No responses yet"} />
            <StatTile icon={Clock3} label="Average response time" value={data.latency?.measured ? `${(data.latency.averageMs / 1000).toFixed(1)}s` : "—"} detail={data.latency?.measured ? `Slowest ${(data.latency.maxMs / 1000).toFixed(1)}s` : undefined} />
            <StatTile icon={BarChart3} label="Open review cases" value={data.reviews ? String(openReviews) : "—"} detail={data.reviews ? `${data.reviews.total} opened in range` : undefined} />
            <StatTile icon={up >= down ? ThumbsUp : ThumbsDown} label="Answer feedback" value={data.feedback ? `${up} / ${down}` : "—"} detail="Helpful / reported" />
          </div>

          <Panel title="Questions per day">
            {data.questionsPerDay ? <DailyChart days={fillDays(data.questionsPerDay, data.since, data.windowDays)} /> : unavailable}
          </Panel>

          <div className="grid gap-4 lg:grid-cols-3">
            <Panel title="Outcomes" subtitle="How each question ended">
              {data.outcomes ? <RankedBars rows={data.outcomes} empty="No responses in this range." /> : unavailable}
            </Panel>
            <Panel title="Risk levels" subtitle="As classified on arrival">
              {data.riskLevels ? <RankedBars rows={data.riskLevels} empty="No questions in this range." /> : unavailable}
            </Panel>
            <Panel title="Routes" subtitle="Which path answered">
              {data.routes ? <RankedBars rows={data.routes} empty="No responses in this range." /> : unavailable}
            </Panel>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="Topics" subtitle={data.answers ? `From ${data.answers.answersSampled} recorded answers` : undefined}>
              {data.answers ? <RankedBars rows={data.answers.topics} empty="No recorded answers in this range." /> : unavailable}
            </Panel>
            <Panel title="Source websites" subtitle={data.answers ? `Answers citing each site, of ${data.answers.answersSampled}` : undefined}>
              {data.answers ? <RankedBars rows={data.answers.sourceSites} empty="No web sources recorded in this range." /> : unavailable}
            </Panel>
          </div>

          <Panel title="Workspace output">
            {data.workspace ? (
              <dl className="grid gap-3 text-sm sm:grid-cols-4">
                <div><dt className="text-xs text-muted">Saved answers</dt><dd className="mt-0.5 text-lg font-semibold text-ink">{data.workspace.savedAnswers}</dd></div>
                <div><dt className="text-xs text-muted">Drafts worked on</dt><dd className="mt-0.5 text-lg font-semibold text-ink">{Object.values(data.workspace.draftsByStatus).reduce((a, b) => a + b, 0)}</dd>
                  <dd className="text-xs text-muted">{Object.entries(data.workspace.draftsByStatus).map(([s, n]) => `${n} ${s}`).join(" · ") || "none"}</dd></div>
                <div><dt className="text-xs text-muted">CPD logged</dt><dd className="mt-0.5 text-lg font-semibold text-ink">{(data.workspace.cpdMinutes / 60).toFixed(1)}h</dd>
                  <dd className="text-xs text-muted">{data.workspace.cpdEntries} entries</dd></div>
                <div><dt className="text-xs text-muted">Review cases</dt><dd className="mt-0.5 text-lg font-semibold text-ink">{data.reviews?.total ?? "—"}</dd>
                  <dd className="text-xs text-muted">{data.reviews ? Object.entries(data.reviews.bySource).map(([s, n]) => `${n} ${pretty(s).toLowerCase()}`).join(" · ") || "none" : ""}</dd></div>
              </dl>
            ) : unavailable}
          </Panel>
        </div>
      )}
    </PageShell>
  );
}
