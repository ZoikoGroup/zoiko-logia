"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, CalendarDays, CalendarPlus, ExternalLink, Loader2 } from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { Pill } from "@/components/governance/Pill";
import { PanelHeader, PANEL_CLASS } from "@/components/governance/PanelHeader";
import { getComplianceCalendar, type ComplianceCalendar, type Deadline } from "@/lib/accounting-workflows-api";

const RANGES = [30, 90, 365];

function urgency(daysLeft: number): { label: string; tone: "bad" | "warn" | "info" } {
  if (daysLeft === 0) return { label: "Due today", tone: "bad" };
  if (daysLeft <= 7) return { label: `${daysLeft} day${daysLeft === 1 ? "" : "s"} left`, tone: "warn" };
  return { label: `${daysLeft} days left`, tone: "info" };
}

const dueLabel = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
const monthLabel = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, { month: "long", year: "numeric", timeZone: "UTC" });

/** An .ics file of the listed deadlines, for Outlook / Google Calendar. */
function downloadIcs(deadlines: Deadline[]) {
  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+/, "");
  const esc = (s: string) => s.replace(/[\\,;]/g, (c) => `\\${c}`).replace(/\n/g, "\\n");
  const events = deadlines.map((d) => {
    const day = d.dueDate.replace(/-/g, "");
    const next = new Date(`${d.dueDate}T00:00:00Z`);
    next.setUTCDate(next.getUTCDate() + 1);
    return [
      "BEGIN:VEVENT", `UID:${d.id}@zoikologia`, `DTSTAMP:${stamp}`,
      `DTSTART;VALUE=DATE:${day}`, `DTEND;VALUE=DATE:${next.toISOString().slice(0, 10).replace(/-/g, "")}`,
      `SUMMARY:${esc(`${d.jurisdiction}: ${d.title}`)}`,
      `DESCRIPTION:${esc(`${d.assumes} Source: ${d.source}`)}`,
      "END:VEVENT",
    ].join("\r\n");
  });
  const ics = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ZoikoLogia//Compliance Calendar//EN", ...events, "END:VCALENDAR"].join("\r\n");
  const url = URL.createObjectURL(new Blob([ics], { type: "text/calendar" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "compliance-deadlines.ics";
  link.click();
  URL.revokeObjectURL(url);
}

export default function ComplianceCalendarPage() {
  const [days, setDays] = useState(90);
  const [jurisdiction, setJurisdiction] = useState("");
  const [data, setData] = useState<ComplianceCalendar | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    getComplianceCalendar(days, jurisdiction, controller.signal)
      .then((result) => { setData(result); setError(""); })
      .catch((err) => { if (err?.name !== "AbortError") setError("Could not load the compliance calendar."); })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [days, jurisdiction]);

  const byMonth = new Map<string, Deadline[]>();
  for (const d of data?.deadlines ?? []) {
    const key = d.dueDate.slice(0, 7);
    byMonth.set(key, [...(byMonth.get(key) ?? []), d]);
  }
  const soon = (data?.deadlines ?? []).filter((d) => d.daysLeft <= 7).length;

  return (
    <PageShell title="Compliance Calendar" subtitle="Upcoming statutory filing and payment deadlines, each with its official source." showMetrics={false}>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex rounded-lg border border-line p-0.5" role="group" aria-label="Country">
          {["", ...(data?.jurisdictions ?? ["India", "UK", "US"])].map((j) => (
            <button key={j || "all"} onClick={() => { setLoading(true); setJurisdiction(j); }} aria-pressed={jurisdiction === j}
              className={`rounded-md px-3 py-1 text-xs font-medium ${jurisdiction === j ? "bg-brand/10 text-brand" : "text-muted hover:bg-soft"}`}>
              {j || "All"}
            </button>
          ))}
        </div>
        <div className="flex rounded-lg border border-line p-0.5" role="group" aria-label="Time range">
          {RANGES.map((r) => (
            <button key={r} onClick={() => { setLoading(true); setDays(r); }} aria-pressed={days === r}
              className={`rounded-md px-3 py-1 text-xs font-medium ${days === r ? "bg-brand/10 text-brand" : "text-muted hover:bg-soft"}`}>
              {r === 365 ? "Next 12 months" : `Next ${r} days`}
            </button>
          ))}
        </div>
        {data && data.deadlines.length > 0 && (
          <button onClick={() => downloadIcs(data.deadlines)}
            className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-ink hover:bg-soft">
            <CalendarPlus size={13} /> Add to calendar (.ics)
          </button>
        )}
      </div>

      {data && (
        <p className="mb-3 flex items-start gap-2 rounded-xl border border-warn/30 bg-warn/10 px-4 py-2 text-xs text-warn">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" /> {data.disclaimer} Verify with a qualified professional before relying on a date.
        </p>
      )}
      {error && <p className="mb-3 text-sm text-bad" role="alert">{error}</p>}

      {loading && !data ? (
        <div className="flex items-center justify-center py-16 text-muted"><Loader2 className="mr-2 animate-spin" size={16} /> Loading deadlines…</div>
      ) : data && (
        <div className={`space-y-4 ${loading ? "opacity-60" : ""}`}>
          <p className="text-sm text-ink">
            <strong>{data.deadlines.length}</strong> deadline{data.deadlines.length === 1 ? "" : "s"} from {dueLabel(data.from)} to {dueLabel(data.to)}
            {soon > 0 && <> · <span className="font-semibold text-warn">{soon} within 7 days</span></>}
          </p>
          {data.deadlines.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted">No deadlines in this range.</p>
          ) : (
            [...byMonth.entries()].map(([month, items]) => (
              <div key={month} className={PANEL_CLASS}>
                <PanelHeader icon={CalendarDays} title={monthLabel(`${month}-01`)} subtitle={`${items.length} deadline${items.length === 1 ? "" : "s"}`} />
                <ul className="divide-y divide-line">
                  {items.map((d) => {
                    const u = urgency(d.daysLeft);
                    return (
                      <li key={d.id} className="grid gap-1 py-3 sm:grid-cols-[150px_minmax(0,1fr)_auto] sm:items-start sm:gap-4">
                        <span className="text-sm font-semibold text-ink">{dueLabel(d.dueDate)}</span>
                        <span className="min-w-0">
                          <span className="block text-sm font-medium text-ink">{d.title}</span>
                          <span className="mt-0.5 block text-xs text-muted">{d.assumes}</span>
                          {d.weekendNote && <span className="mt-0.5 block text-xs text-warn">Falls on a weekend. {d.weekendNote}</span>}
                          <a href={d.source} target="_blank" rel="noreferrer" className="mt-0.5 inline-flex items-center gap-1 text-xs text-brand hover:underline">
                            <ExternalLink size={11} /> Official source
                          </a>
                        </span>
                        <span className="flex flex-wrap items-center gap-1.5 sm:justify-end">
                          <Pill>{d.jurisdiction}</Pill>
                          <Pill>{d.category}</Pill>
                          <Pill tone={u.tone}>{u.label}</Pill>
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))
          )}
        </div>
      )}
    </PageShell>
  );
}
