"use client";

import { useEffect, useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  AlertTriangle, BarChart3, Briefcase, CalendarRange, CheckCircle2, ClipboardCheck, Clock3, Database, Gauge, GitBranch, Globe,
  MessageSquare, ShieldAlert, ShieldCheck, Tags, ThumbsDown, ThumbsUp,
} from "lucide-react";
import {
  Badge, Callout, ControlNote, Empty, ErrorNote, FilterTabs, Hero, InfoCards, Inspector, KeyGrid, LifecycleSteps, ListItem, Loading,
  Panel, RegisterHead, RegisterRow, Stack, StatCard, StatGrid, WorkflowPage, type Tone,
} from "@/components/workflow-ui/kit";
import { getInsights, type Count, type Insights } from "@/lib/insights-api";

const WINDOWS = [7, 30, 90];

const SECTION_NAMES: Record<string, string> = {
  questionsPerDay: "questions per day", outcomes: "outcomes", routes: "routes", riskLevels: "risk levels",
  latency: "response time", answers: "topics and sources", reviews: "review cases", feedback: "feedback",
  workspace: "workspace output",
};

const pretty = (label: string) => label.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
const sum = (rows: Count[]) => rows.reduce((s, r) => s + r.count, 0);
const toCounts = (record: Record<string, number>) =>
  Object.entries(record).map(([label, count]) => ({ label, count })).sort((a, b) => b.count - a.count);
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

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
        <button onClick={() => setAsTable((v) => !v)} className="font-semibold text-info hover:underline">{asTable ? "Show chart" : "Show table"}</button>
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
                  className={`w-full rounded-t-[4px] ${hover === i ? "bg-accent" : "bg-info"}`}
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
  if (!rows.length) return <p className="py-3 text-xs text-muted">{empty}</p>;
  const max = Math.max(...rows.map((r) => r.count));
  const total = sum(rows);
  return (
    <ul className="space-y-2">
      {rows.map((r) => (
        <li key={r.label} title={`${pretty(r.label)}: ${r.count} (${Math.round((r.count / total) * 100)}%)`}>
          <div className="flex justify-between gap-2 text-xs">
            <span className="truncate text-ink">{pretty(r.label)}</span>
            <span className="shrink-0 tabular-nums text-muted">{r.count} · {Math.round((r.count / total) * 100)}%</span>
          </div>
          <div className="mt-1 h-1.5 rounded-full bg-soft">
            <div className="h-full rounded-full bg-info" style={{ width: `${(r.count / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

const notRead = <p className="py-3 text-xs text-muted">Not available right now.</p>;

// ── Report sections: one register row per section the backend returns ───────

type SectionKey = "outcomes" | "riskLevels" | "routes" | "topics" | "sourceSites" | "reviews" | "feedback" | "workspace";
type Section = {
  key: SectionKey; backendKey: string; name: string; description: string; source: string; lineage: string;
  icon: LucideIcon; rows: Count[] | null; records: string | null; empty: string;
};

function sections(data: Insights): Section[] {
  const a = data.answers;
  return [
    { key: "outcomes", backendKey: "outcomes", name: "Outcomes", description: "How each response ended", source: "Audit ledger",
      lineage: "Response-finalised events in the audit ledger", icon: CheckCircle2, rows: data.outcomes,
      records: data.outcomes && plural(sum(data.outcomes), "response"), empty: "No responses in this range." },
    { key: "riskLevels", backendKey: "riskLevels", name: "Risk levels", description: "As classified on arrival", source: "Audit ledger",
      lineage: "Risk-classified events in the audit ledger", icon: ShieldAlert, rows: data.riskLevels,
      records: data.riskLevels && plural(sum(data.riskLevels), "question"), empty: "No questions in this range." },
    { key: "routes", backendKey: "routes", name: "Routes", description: "Which path answered", source: "Audit ledger",
      lineage: "Response-finalised events in the audit ledger", icon: GitBranch, rows: data.routes,
      records: data.routes && plural(sum(data.routes), "response"), empty: "No responses in this range." },
    { key: "topics", backendKey: "answers", name: "Topics", description: "Detected in recorded answers", source: "Recorded answers",
      lineage: "The most recent recorded answers (up to 500)", icon: Tags, rows: a?.topics ?? null,
      records: a && `${plural(a.answersSampled, "answer")} read`, empty: "No recorded answers in this range." },
    { key: "sourceSites", backendKey: "answers", name: "Source websites", description: "Answers citing each site", source: "Recorded answers",
      lineage: "Web sources stored with the most recent recorded answers (up to 500)", icon: Globe, rows: a?.sourceSites ?? null,
      records: a && `${plural(a.answersSampled, "answer")} read`, empty: "No web sources recorded in this range." },
    { key: "reviews", backendKey: "reviews", name: "Review cases", description: "Opened in the period, by status", source: "Review cases",
      lineage: "Review cases opened in the period", icon: ClipboardCheck, rows: data.reviews ? toCounts(data.reviews.byStatus) : null,
      records: data.reviews && plural(data.reviews.total, "case"), empty: "No review cases opened in this range." },
    { key: "feedback", backendKey: "feedback", name: "Answer feedback", description: "Helpful and reported ratings", source: "Feedback",
      lineage: "Ratings people gave answers in the period", icon: ThumbsUp,
      rows: data.feedback ? toCounts(data.feedback).map((r) => ({ ...r, label: r.label === "up" ? "helpful" : r.label === "down" ? "reported" : r.label })) : null,
      records: data.feedback && plural(sum(toCounts(data.feedback)), "rating"), empty: "No answer feedback in this range." },
    { key: "workspace", backendKey: "workspace", name: "Workspace output", description: "Saved answers, drafts and CPD", source: "Workspace",
      lineage: "Saved answers created, drafts updated and CPD entries logged in the period", icon: Briefcase,
      rows: data.workspace ? toCounts(data.workspace.draftsByStatus) : null,
      records: data.workspace && plural(data.workspace.savedAnswers, "saved answer"), empty: "No drafts worked on in this range." },
  ];
}

const TEMPLATE = "md:grid-cols-[minmax(0,2.2fr)_minmax(0,1.1fr)_minmax(0,1.1fr)_minmax(0,0.9fr)]";
type Tab = "all" | "available" | "not_read";

export default function ReportsInsightsPage() {
  const [windowDays, setWindowDays] = useState(30);
  const [data, setData] = useState<Insights | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("all");
  const [selectedKey, setSelectedKey] = useState<SectionKey>("outcomes");

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

  const finalised = sum(data?.outcomes ?? []);
  const answered = data?.outcomes?.find((r) => r.label === "answered")?.count ?? 0;
  const up = data?.feedback?.up ?? 0;
  const down = data?.feedback?.down ?? 0;
  const openReviews = (data?.reviews?.byStatus.open ?? 0) + (data?.reviews?.byStatus.needs_evidence ?? 0);

  const all = data ? sections(data) : [];
  const isRead = (s: Section) => s.rows !== null && !data?.unavailable.includes(s.backendKey);
  const visible = all.filter((s) => tab === "all" || (tab === "available" ? isRead(s) : !isRead(s)));
  const current = visible.find((s) => s.key === selectedKey) ?? visible[0];
  const period = data ? `Last ${data.windowDays} days` : `Last ${windowDays} days`;
  const generated = data ? new Date(data.generatedAt).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";

  // Exceptions worth a look, each read from a section that came back.
  const watchlist: { key: SectionKey; title: string; detail: string; tone: Tone; badge: string }[] = data ? [
    ...(data.outcomes ?? []).filter((r) => r.label !== "answered" && r.count > 0).map((r) => ({
      key: "outcomes" as const, title: `${plural(r.count, "response")} ${pretty(r.label).toLowerCase()}`,
      detail: `Outcome recorded in the audit ledger · ${period.toLowerCase()}`, tone: "warn" as const, badge: "Outcome" })),
    ...(data.riskLevels ?? []).filter((r) => /high|critical/i.test(r.label) && r.count > 0).map((r) => ({
      key: "riskLevels" as const, title: `${plural(r.count, "question")} classified ${pretty(r.label.toLowerCase())}`,
      detail: "Risk level given on arrival", tone: "bad" as const, badge: "Risk" })),
    ...(openReviews > 0 ? [{ key: "reviews" as const, title: `${plural(openReviews, "review case")} still open`,
      detail: "Open or waiting for evidence", tone: "warn" as const, badge: "Review" }] : []),
    ...(down > 0 ? [{ key: "feedback" as const, title: `${plural(down, "answer")} reported`,
      detail: "Marked not helpful by the person who asked", tone: "bad" as const, badge: "Feedback" }] : []),
  ] : [];

  return (
    <WorkflowPage section="Accounting Workflows" title="Reports & Insights"
      subtitle="Decision intelligence, reporting readiness, and explainable accounting performance—backed by Kriton's own records."
      note={data ? `Updated ${new Date(data.generatedAt).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}` : undefined}>
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-panel px-3 py-2.5 shadow-[0_4px_14px_rgba(13,34,64,0.04)]">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-accent/12 text-accent-ink"><CalendarRange size={17} /></span>
        <span className="min-w-0">
          <span className="block text-[10px] text-muted">Reporting period</span>
          <span className="block text-sm font-semibold text-ink">{period}</span>
        </span>
        <div className="ml-auto flex rounded-lg border border-line bg-soft/60 p-0.5" role="group" aria-label="Time range">
          {WINDOWS.map((d) => (
            <button key={d} type="button" onClick={() => chooseWindow(d)} aria-pressed={windowDays === d}
              className={`rounded-md px-3 py-1.5 text-xs font-bold transition ${windowDays === d ? "bg-panel text-accent-ink shadow-sm" : "text-muted hover:text-ink"}`}>
              Last {d} days
            </button>
          ))}
        </div>
      </div>

      <Hero icon={BarChart3} eyebrow="Governed reporting · Explainable metrics · Professional judgment" title="See what matters. Trace every conclusion."
        subtitle="Usage, outcomes, review and feedback read from Kriton's own records for the selected period."
        aside={<LifecycleSteps title="Insight assurance path" steps={["Questions", "Answers", "Reviews", "Feedback"]} />} />

      {error && <ErrorNote message={error} />}
      {data && data.unavailable.length > 0 && (
        <Callout tone="warn" title={`Some sections could not be read in time: ${data.unavailable.map((s) => SECTION_NAMES[s] ?? s).join(", ")}.`} />
      )}

      {loading && !data ? <Loading>Loading insights…</Loading> : data && (
        <div className={`space-y-4 ${loading ? "opacity-60" : ""}`}>
          <StatGrid>
            <StatCard icon={MessageSquare} tone="info" value={data.totalQuestions === null ? "—" : String(data.totalQuestions)} label="Questions asked" hint={`Last ${data.windowDays} days`} />
            <StatCard icon={ShieldCheck} tone="ok" value={finalised ? `${Math.round((answered / finalised) * 100)}%` : "—"} label="Answered"
              hint={finalised ? `${answered} of ${finalised} responses` : "No responses yet"} />
            <StatCard icon={Clock3} tone="neutral" value={data.latency?.measured ? `${(data.latency.averageMs / 1000).toFixed(1)}s` : "—"} label="Average response time"
              hint={data.latency?.measured ? `Slowest ${(data.latency.maxMs / 1000).toFixed(1)}s` : undefined} />
            <StatCard icon={ClipboardCheck} tone="warn" value={data.reviews ? String(openReviews) : "—"} label="Open review cases"
              hint={data.reviews ? `${data.reviews.total} opened in range` : undefined} />
            <StatCard icon={up >= down ? ThumbsUp : ThumbsDown} tone="brand" value={data.feedback ? `${up} / ${down}` : "—"} label="Answer feedback" hint="Helpful / reported" />
          </StatGrid>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
            <div className="min-w-0 space-y-4">
              <Panel title="Reporting assurance overview" subtitle={`Questions received and how responses ended · ${period.toLowerCase()}`}>
                <div className="grid gap-5 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
                  <div className="min-w-0">
                    <p className="mb-2 text-xs font-bold text-accent-ink">Questions per day</p>
                    {data.questionsPerDay ? <DailyChart days={fillDays(data.questionsPerDay, data.since, data.windowDays)} /> : notRead}
                  </div>
                  <div className="min-w-0">
                    <p className="mb-2 text-xs font-bold text-accent-ink">Outcomes by type</p>
                    {data.outcomes ? <RankedBars rows={data.outcomes} empty="No responses in this range." /> : notRead}
                  </div>
                </div>
              </Panel>

              <Panel title="Insight & report register" subtitle="Each report section, where it is read from and whether it came back in time">
                <FilterTabs label="Filter report sections" active={tab} onChange={setTab} tabs={[
                  { key: "all", label: "All insights", count: all.length },
                  { key: "available", label: "Available", count: all.filter(isRead).length },
                  { key: "not_read", label: "Not read", count: all.filter((s) => !isRead(s)).length },
                ]} />
                <div className="mt-3">
                  {visible.length === 0 ? (
                    <Empty icon={BarChart3} title="No sections here">{tab === "not_read" ? "Every section was read in time." : "No section was read in time."}</Empty>
                  ) : (
                    <div className="overflow-hidden rounded-lg border border-line">
                      <RegisterHead template={TEMPLATE} columns={["Insight / report", "Source", "Records", "State"]} />
                      {visible.map((s) => (
                        <RegisterRow key={s.key} template={TEMPLATE} selected={current?.key === s.key} onClick={() => setSelectedKey(s.key)}
                          icon={s.icon} tone={isRead(s) ? "info" : "warn"} title={s.name} subtitle={s.description}
                          cells={[
                            <Stack key="src" main={s.source} sub={period} />,
                            <Stack key="rec" main={isRead(s) ? s.records : "—"} sub={isRead(s) ? undefined : "Not read"} subTone="warn" />,
                            <Badge key="st" tone={isRead(s) ? "ok" : "warn"}>{isRead(s) ? "Available" : "Not read in time"}</Badge>,
                          ]} />
                      ))}
                    </div>
                  )}
                </div>
                <p className="mt-2 text-[11px] text-muted">{visible.length} of {all.length} sections shown</p>
              </Panel>
            </div>

            {!current ? (
              <section className="rounded-xl border border-line bg-panel p-4 shadow-[0_4px_14px_rgba(13,34,64,0.05)]" aria-label="Insight inspector">
                <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted">Insight inspector</p>
                <Empty icon={BarChart3} title="Select a section">Pick a report section to see its figures and where they come from.</Empty>
              </section>
            ) : (
              <Inspector eyebrow="Insight inspector" title={current.name} description={`${current.description}. ${current.lineage}.`}
                badges={<>
                  <Badge tone={isRead(current) ? "ok" : "warn"}>{isRead(current) ? "Available" : "Not read in time"}</Badge>
                  <Badge>{current.source}</Badge>
                  <Badge>{period}</Badge>
                </>}>
                <KeyGrid items={[
                  ["Period", period],
                  ["Source", current.source],
                  ["Records", isRead(current) ? current.records : "—"],
                  ["Generated at", generated],
                ]} />

                {!isRead(current) ? (
                  <Callout tone="warn" title="Not read in time">
                    The backend could not read this section before the report was built. Choose the period again to retry.
                  </Callout>
                ) : current.key === "workspace" && data.workspace ? (
                  <>
                    <dl className="grid grid-cols-3 gap-2">
                      {([
                        ["Saved answers", String(data.workspace.savedAnswers)],
                        ["Drafts worked on", String(sum(current.rows ?? []))],
                        ["CPD logged", `${data.workspace.cpdMinutes} min`],
                      ] as const).map(([k, v]) => (
                        <div key={k} className="rounded-lg border border-line bg-soft/60 p-2.5">
                          <dt className="text-[9px] font-bold uppercase tracking-wider text-muted">{k}</dt>
                          <dd className="mt-0.5 text-sm font-bold text-ink">{v}</dd>
                        </div>
                      ))}
                    </dl>
                    <div>
                      <p className="mb-2 border-b border-line pb-1.5 text-xs font-bold text-accent-ink">Drafts by status</p>
                      <RankedBars rows={current.rows ?? []} empty={current.empty} />
                    </div>
                    <p className="text-[11px] text-muted">{plural(data.workspace.cpdEntries, "CPD entry", "CPD entries")} logged in the period.</p>
                  </>
                ) : (
                  <div>
                    <p className="mb-2 border-b border-line pb-1.5 text-xs font-bold text-accent-ink">Breakdown</p>
                    <RankedBars rows={current.rows ?? []} empty={current.empty} />
                    {current.key === "reviews" && data.reviews && Object.keys(data.reviews.bySource).length > 0 && (
                      <>
                        <p className="mb-2 mt-4 border-b border-line pb-1.5 text-xs font-bold text-accent-ink">By source</p>
                        <RankedBars rows={toCounts(data.reviews.bySource)} empty="" />
                      </>
                    )}
                  </div>
                )}

                <ControlNote><b className="text-ink">Metric control:</b> figures are read from Kriton&apos;s records; nothing here is estimated.</ControlNote>
              </Inspector>
            )}
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Panel title="Material exception watchlist" subtitle="Responses, questions and answers that may need a closer look">
              {watchlist.length === 0 ? <p className="py-3 text-xs text-muted">Nothing to flag in this period.</p> : (
                <ul>{watchlist.map((w) => (
                  <ListItem key={w.title} icon={AlertTriangle} tone={w.tone} title={w.title} detail={w.detail}
                    badge={<Badge tone={w.tone}>{w.badge}</Badge>} onClick={() => { setTab("all"); setSelectedKey(w.key); }} />
                ))}</ul>
              )}
            </Panel>
            <Panel title="Evidence & metric lineage" subtitle="Where each figure on this page is read from">
              <ul>
                <ListItem icon={MessageSquare} tone="info" title="Questions asked & questions per day" detail="Question-received events in the audit ledger" />
                <ListItem icon={Gauge} tone="info" title="Average response time"
                  detail={data.latency ? `Response-returned events · ${plural(data.latency.measured, "response")} measured` : "Not read in time"} />
                {all.map((s) => (
                  <ListItem key={s.key} icon={s.icon} tone={isRead(s) ? "info" : "warn"} title={s.name} detail={s.lineage} />
                ))}
              </ul>
            </Panel>
            <Panel title="Workspace output" subtitle={`Created or updated · ${period.toLowerCase()}`}>
              {data.workspace ? (
                <dl className="grid grid-cols-2 gap-3 text-sm">
                  <div><dt className="text-xs text-muted">Saved answers</dt><dd className="mt-0.5 text-lg font-semibold text-ink">{data.workspace.savedAnswers}</dd></div>
                  <div><dt className="text-xs text-muted">Drafts worked on</dt><dd className="mt-0.5 text-lg font-semibold text-ink">{Object.values(data.workspace.draftsByStatus).reduce((a, b) => a + b, 0)}</dd>
                    <dd className="text-xs text-muted">{Object.entries(data.workspace.draftsByStatus).map(([s, n]) => `${n} ${s}`).join(" · ") || "none"}</dd></div>
                  <div><dt className="text-xs text-muted">CPD logged</dt><dd className="mt-0.5 text-lg font-semibold text-ink">{(data.workspace.cpdMinutes / 60).toFixed(1)}h</dd>
                    <dd className="text-xs text-muted">{plural(data.workspace.cpdEntries, "entry", "entries")}</dd></div>
                  <div><dt className="text-xs text-muted">Review cases</dt><dd className="mt-0.5 text-lg font-semibold text-ink">{data.reviews?.total ?? "—"}</dd>
                    <dd className="text-xs text-muted">{data.reviews ? Object.entries(data.reviews.bySource).map(([s, n]) => `${n} ${pretty(s).toLowerCase()}`).join(" · ") || "none" : ""}</dd></div>
                </dl>
              ) : notRead}
            </Panel>
          </div>
        </div>
      )}

      <InfoCards items={[
        { icon: Database, title: "Read from Kriton's records", text: "Every figure comes from the audit ledger, recorded answers, review cases, feedback and workspace records for the selected period." },
        { icon: ShieldAlert, title: "Gaps are shown, not filled", text: "A section the backend could not read in time is marked as not read; it is never estimated or carried over from another period." },
        { icon: ShieldCheck, title: "Judgment stays with people", text: "These are usage and review signals about Kriton, not an assurance opinion on any client's figures." },
      ]} />
    </WorkflowPage>
  );
}
