"use client";

import { useEffect, useState, type ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import {
  AlertTriangle, CalendarClock, CalendarDays, CalendarPlus, CalendarRange, ChevronDown, ChevronLeft, ChevronRight, ExternalLink,
  Globe2, Landmark, ListFilter, Scale, ShieldCheck,
} from "lucide-react";
import {
  Badge, Btn, Callout, CheckRow, Checklist, ControlNote, Empty, ErrorNote, FilterTabs, InfoCards, Inspector, KeyGrid, Loading,
  Panel, RegisterHead, SearchField, StatCard, StatGrid, WorkflowPage, type Tone,
} from "@/components/workflow-ui/kit";
import { getComplianceCalendar, type ComplianceCalendar, type Deadline } from "@/lib/accounting-workflows-api";

const RANGES = [30, 90, 365];
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const TEMPLATE = "md:grid-cols-[minmax(0,2.2fr)_minmax(0,1.1fr)_minmax(0,0.8fr)_minmax(0,1.7fr)]";
type Tab = "all" | "week" | "month" | "weekend";

function urgency(daysLeft: number): { label: string; tone: "bad" | "warn" | "info" } {
  if (daysLeft === 0) return { label: "Due today", tone: "bad" };
  if (daysLeft <= 7) return { label: `${daysLeft} day${daysLeft === 1 ? "" : "s"} left`, tone: "warn" };
  return { label: `${daysLeft} days left`, tone: "info" };
}

/** Colour band of a deadline: within 7 days, within 30 days, later. */
function band(daysLeft: number): { label: string; tone: Tone; chip: string } {
  if (daysLeft <= 7) return { label: "Within 7 days", tone: "bad", chip: "bg-bad/12 text-bad" };
  if (daysLeft <= 30) return { label: "Within 30 days", tone: "warn", chip: "bg-accent/14 text-accent-ink" };
  return { label: "Later", tone: "info", chip: "bg-info/12 text-info" };
}

const dueLabel = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
const fullDate = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const monthLabel = (key: string) =>
  new Date(`${key}-01T00:00:00Z`).toLocaleDateString(undefined, { month: "long", year: "numeric", timeZone: "UTC" });
function shiftMonth(key: string, n: number) {
  const [y, m] = key.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1 + n, 1)).toISOString().slice(0, 7);
}
function todayIso() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}
const host = (url: string) => { try { return new URL(url).hostname; } catch { return url; } };

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

/** A scope-bar card holding its own control (segmented buttons or a select). */
function ScopeCard({ icon: Icon, label, children }: { icon: LucideIcon; label: string; children: ReactNode }) {
  return (
    <div className="relative flex min-w-0 items-center gap-3 rounded-xl border border-line bg-panel px-3 py-2.5 shadow-[0_4px_14px_rgba(13,34,64,0.04)]">
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-accent/12 text-accent-ink"><Icon size={17} /></span>
      <span className="min-w-0 flex-1">
        <span className="block text-[10px] text-muted">{label}</span>
        <span className="mt-1 block">{children}</span>
      </span>
    </div>
  );
}

function Segmented<T extends string | number>({ label, options, value, onChange }: {
  label: string; options: { value: T; label: string }[]; value: T; onChange: (v: T) => void;
}) {
  return (
    <span role="group" aria-label={label} className="inline-flex flex-wrap rounded-lg border border-line bg-soft/60 p-0.5">
      {options.map((o) => (
        <button key={String(o.value) || "all"} type="button" onClick={() => onChange(o.value)} aria-pressed={value === o.value}
          className={`rounded-md px-2.5 py-1 text-xs font-semibold transition ${value === o.value ? "bg-panel text-accent-ink shadow-sm" : "text-muted hover:text-ink"}`}>
          {o.label}
        </button>
      ))}
    </span>
  );
}

/** Mon–Sun month grid with each deadline on its due day. */
function MonthGrid({ month, deadlines, today, selectedId, onSelect }: {
  month: string; deadlines: Deadline[]; today: string; selectedId?: string; onSelect: (id: string) => void;
}) {
  const [y, m] = month.split("-").map(Number);
  const lead = (new Date(Date.UTC(y, m - 1, 1)).getUTCDay() + 6) % 7;
  const daysIn = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const cells = Array.from({ length: Math.ceil((lead + daysIn) / 7) * 7 }, (_, i) => i - lead + 1);
  const byDay = new Map<number, Deadline[]>();
  for (const d of deadlines) {
    if (d.dueDate.slice(0, 7) !== month) continue;
    const day = Number(d.dueDate.slice(8, 10));
    byDay.set(day, [...(byDay.get(day) ?? []), d]);
  }
  return (
    <div className="overflow-hidden rounded-lg border border-line">
      <div aria-hidden className="grid grid-cols-7 bg-soft text-center text-[10px] font-bold uppercase tracking-wider text-muted">
        {WEEKDAYS.map((w) => <span key={w} className="py-1.5">{w}</span>)}
      </div>
      <div className="grid grid-cols-7">
        {cells.map((day, i) => {
          const inMonth = day >= 1 && day <= daysIn;
          const iso = inMonth ? `${month}-${String(day).padStart(2, "0")}` : "";
          const items = byDay.get(day) ?? [];
          const isToday = iso === today;
          return (
            <div key={i} className={`min-h-19 min-w-0 border-line p-1 ${i % 7 ? "border-l" : ""} ${i >= 7 ? "border-t" : ""} ${inMonth ? "" : "bg-soft/40"} ${isToday ? "bg-accent/5" : ""}`}>
              {inMonth && (
                <>
                  <span className={`inline-grid h-5 min-w-5 place-items-center rounded-full px-1 text-[11px] font-semibold ${isToday ? "bg-accent text-white" : i % 7 >= 5 ? "text-muted" : "text-ink"}`}>{day}</span>
                  <div className="mt-0.5 space-y-0.5">
                    {items.slice(0, 2).map((d) => (
                      <button key={d.id} type="button" title={d.title} onClick={() => onSelect(d.id)} aria-current={selectedId === d.id || undefined}
                        className={`block w-full truncate rounded px-1 py-0.5 text-left text-[10px] font-bold ${band(d.daysLeft).chip} ${selectedId === d.id ? "ring-1 ring-accent" : ""}`}>
                        {`${d.jurisdiction} · ${d.category}`}
                      </button>
                    ))}
                    {items.length > 2 && <span className="block px-1 text-[10px] text-muted">+{items.length - 2} more</span>}
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function ComplianceCalendarPage() {
  const [days, setDays] = useState(90);
  const [jurisdiction, setJurisdiction] = useState("");
  const [data, setData] = useState<ComplianceCalendar | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [category, setCategory] = useState("");
  const [tab, setTab] = useState<Tab>("all");
  const [query, setQuery] = useState("");
  const [month, setMonth] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    getComplianceCalendar(days, jurisdiction, controller.signal)
      .then((result) => { setData(result); setError(""); })
      .catch((err) => { if (err?.name !== "AbortError") setError("Could not load the compliance calendar."); })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [days, jurisdiction]);

  const all = data?.deadlines ?? [];
  const categories = [...new Set([...all.map((d) => d.category), ...(category ? [category] : [])])].sort();
  const scoped = all.filter((d) => !category || d.category === category);
  const soon = scoped.filter((d) => d.daysLeft <= 7).length;
  const inTab = (d: Deadline) => tab === "all" || (tab === "week" ? d.daysLeft <= 7 : tab === "month" ? d.daysLeft <= 30 : !!d.weekendNote);
  const needle = query.trim().toLowerCase();
  const visible = scoped.filter((d) => inTab(d)
    && (!needle || [d.title, d.jurisdiction, d.category].some((s) => s.toLowerCase().includes(needle))));
  const selected = scoped.find((d) => d.id === selectedId) ?? visible[0] ?? scoped[0] ?? null;

  const today = todayIso();
  const first = data ? data.from.slice(0, 7) : today.slice(0, 7);
  const last = data ? data.to.slice(0, 7) : first;
  const clamp = (key: string) => (key < first ? first : key > last ? last : key);
  const shown = clamp(month ?? first);

  const pickJurisdiction = (j: string) => { setLoading(true); setJurisdiction(j); };
  const pickRange = (r: number) => { setLoading(true); setDays(r); };

  return (
    <WorkflowPage section="Accounting Workflows" title="Compliance Calendar"
      subtitle="Track obligations, verify applicability, resolve evidence gaps, and deliver on deadlines with accountable approvals.">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <ScopeCard icon={Globe2} label="Jurisdiction">
          <Segmented label="Country" value={jurisdiction} onChange={pickJurisdiction}
            options={["", ...(data?.jurisdictions ?? ["India", "UK", "US"])].map((j) => ({ value: j, label: j || "All" }))} />
        </ScopeCard>
        <ScopeCard icon={ListFilter} label="Obligation category">
          <span className="relative block">
            <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Obligation category"
              className="w-full cursor-pointer appearance-none truncate bg-transparent pr-6 text-sm font-semibold text-ink outline-none">
              <option value="">All obligation categories</option>
              {categories.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <ChevronDown aria-hidden size={16} className="pointer-events-none absolute right-0 top-0.5 text-ink" />
          </span>
        </ScopeCard>
        <ScopeCard icon={CalendarRange} label="Calendar scope">
          <Segmented label="Time range" value={days} onChange={pickRange}
            options={RANGES.map((r) => ({ value: r, label: r === 365 ? "Next 12 months" : `Next ${r} days` }))} />
        </ScopeCard>
      </div>

      <StatGrid>
        <StatCard icon={CalendarDays} tone="info" value={scoped.length} label="Scoped obligations" hint="In the selected range and scope" />
        <StatCard icon={AlertTriangle} tone="bad" value={soon} label="Due in next 7 days" hint="Including anything due today" />
        <StatCard icon={CalendarClock} tone="warn" value={scoped.filter((d) => d.daysLeft <= 30).length} label="Due within 30 days" hint="Counted from today" />
        <StatCard icon={Scale} tone="neutral" value={scoped.filter((d) => d.weekendNote).length} label="Weekend-adjusted dates" hint="Carry an official weekend rule" />
        <StatCard icon={Landmark} tone="ok" value={new Set(scoped.map((d) => d.jurisdiction)).size} label="Jurisdictions covered"
          hint={[...new Set(scoped.map((d) => d.jurisdiction))].join(", ") || "None in scope"} />
      </StatGrid>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-line bg-panel px-4 py-2.5 text-[11px] text-muted">
        <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-accent-ink">Before relying on a date</span>
        <ol className="flex flex-wrap items-center gap-1.5">
          {["Read the official source", "Check it applies to you", "Give it an owner in your team", "File or pay on time"].map((step, i, list) => (
            <li key={step} className="flex items-center gap-1.5">
              <span className="grid h-4 w-4 place-items-center rounded-full bg-chip text-[9px] font-bold text-ink">{i + 1}</span>
              {step}{i < list.length - 1 && <span aria-hidden className="text-accent-ink">→</span>}
            </li>
          ))}
        </ol>
      </div>

      {error && <ErrorNote message={error} />}

      {loading && !data ? <Loading>Loading deadlines…</Loading> : data && (
        <div className={`grid gap-4 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)] ${loading ? "opacity-60" : ""}`}>
          <div className="min-w-0 space-y-4">
            <Panel title="Obligation calendar" subtitle="Statutory deadlines on their due day · select one to inspect it"
              actions={<>
                <Btn variant="quiet" label="Previous month" disabled={shown <= first} onClick={() => setMonth(shiftMonth(shown, -1))}><ChevronLeft size={14} /></Btn>
                <span className="inline-flex min-h-9 items-center px-1 text-sm font-bold text-ink">{monthLabel(shown)}</span>
                <Btn variant="quiet" label="Next month" disabled={shown >= last} onClick={() => setMonth(shiftMonth(shown, 1))}><ChevronRight size={14} /></Btn>
                <Btn onClick={() => setMonth(clamp(today.slice(0, 7)))}>Today</Btn>
              </>}>
              <MonthGrid month={shown} deadlines={scoped} today={today} selectedId={selected?.id} onSelect={setSelectedId} />
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted">
                {[["bg-bad", "Due within 7 days"], ["bg-accent", "Within 30 days"], ["bg-info", "Later"]].map(([dot, text]) => (
                  <span key={text} className="inline-flex items-center gap-1.5"><span aria-hidden className={`h-2 w-2 rounded-full ${dot}`} />{text}</span>
                ))}
              </div>
            </Panel>

            <Panel title="Priority obligation queue" subtitle="Soonest first, each with its official source"
              actions={scoped.length > 0 && <Btn onClick={() => downloadIcs(scoped)}><CalendarPlus size={13} /> Add to calendar (.ics)</Btn>}
              footer={<span>Showing {visible.length} of {scoped.length} deadlines</span>}>
              <p className="mb-3 text-sm text-ink">
                <strong>{scoped.length}</strong> deadline{scoped.length === 1 ? "" : "s"} from {dueLabel(data.from)} to {dueLabel(data.to)}
                {soon > 0 && <> · <span className="font-semibold text-bad">{soon} within 7 days</span></>}
              </p>
              <FilterTabs label="Filter deadlines" active={tab} onChange={setTab} tabs={[
                { key: "all", label: "All", count: scoped.length },
                { key: "week", label: "Due in 7 days", count: soon },
                { key: "month", label: "Due in 30 days", count: scoped.filter((d) => d.daysLeft <= 30).length },
                { key: "weekend", label: "Weekend-adjusted", count: scoped.filter((d) => d.weekendNote).length },
              ]} />
              <div className="my-3 flex gap-2">
                <SearchField value={query} onChange={setQuery} placeholder="Search obligation, jurisdiction or category" label="Search deadlines" />
              </div>

              {visible.length === 0 ? (
                <Empty icon={CalendarDays} title={all.length ? "No deadlines match" : "No deadlines in this range"}>
                  {all.length ? "Change the scope, tab or search." : "Try a longer range or another jurisdiction."}
                </Empty>
              ) : (
                <div className="overflow-hidden rounded-lg border border-line">
                  <RegisterHead template={TEMPLATE} columns={["Obligation / authority", "Due · type", "Source", "Notes"]} />
                  {visible.map((d) => {
                    const u = urgency(d.daysLeft);
                    const isSelected = selected?.id === d.id;
                    return (
                      <div key={d.id} className={`grid gap-x-3 gap-y-1.5 border-b border-line px-3 py-3 transition last:border-b-0 hover:bg-soft md:items-center ${TEMPLATE} ${isSelected ? "bg-accent/5 shadow-[inset_3px_0_0_var(--accent)]" : ""}`}>
                        <button type="button" onClick={() => setSelectedId(d.id)} aria-current={isSelected || undefined} className="flex min-w-0 items-start gap-3 text-left">
                          <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg ${band(d.daysLeft).chip}`}><CalendarDays size={15} /></span>
                          <span className="min-w-0">
                            <span className="block truncate text-sm font-semibold text-ink">{d.title}</span>
                            <span className="mt-0.5 block truncate text-[11px] text-muted">{`${d.jurisdiction} · ${d.category}`}</span>
                          </span>
                        </button>
                        <span className="min-w-0 pl-11 text-xs md:pl-0">
                          <span className="block font-semibold text-ink">{dueLabel(d.dueDate)}</span>
                          <span className="mt-0.5 block"><Badge tone={u.tone}>{u.label}</Badge></span>
                        </span>
                        <span className="min-w-0 pl-11 text-xs md:pl-0">
                          <a href={d.source} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[11px] font-bold text-info hover:underline">
                            <ExternalLink size={11} /> Official source
                          </a>
                        </span>
                        <span className="min-w-0 pl-11 text-[11px] md:pl-0">
                          <span className="block text-muted">{d.assumes}</span>
                          {d.weekendNote && <span className="mt-0.5 block text-accent-ink">Falls on a weekend. {d.weekendNote}</span>}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </Panel>
          </div>

          {!selected ? (
            <section className="rounded-xl border border-line bg-panel p-4 shadow-[0_4px_14px_rgba(13,34,64,0.05)]" aria-label="Obligation inspector">
              <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted">Obligation inspector</p>
              <Empty icon={CalendarDays} title="No deadline selected">Pick a deadline in the calendar or the queue to see its source and rules.</Empty>
              <Callout title="General statutory deadlines">{data.disclaimer} Verify with a qualified professional before relying on a date.</Callout>
            </section>
          ) : (
            <Inspector eyebrow="Obligation inspector · selected record" title={`${selected.jurisdiction}: ${selected.title}`}
              badges={<>
                <Badge tone="info">{selected.jurisdiction}</Badge>
                <Badge>{selected.category}</Badge>
                <Badge tone={band(selected.daysLeft).tone}>{selected.daysLeft === 0 ? "Due today" : band(selected.daysLeft).label}</Badge>
              </>}
              description="A general statutory deadline from the official rule, not an obligation recorded for your organisation.">
              <KeyGrid items={[
                ["Due date", fullDate(selected.dueDate)],
                ["Days left", String(selected.daysLeft)],
                ["Jurisdiction", selected.jurisdiction],
                ["Category", selected.category],
              ]} />

              <div>
                <p className="mb-1 border-b border-line pb-1.5 text-xs font-bold text-accent-ink">Obligation assurance</p>
                <Checklist>
                  <CheckRow state="pass" title="Applicable source"
                    detail={<a href={selected.source} target="_blank" rel="noreferrer" className="text-info hover:underline">{host(selected.source)}</a>} right="Official" />
                  <CheckRow state="warn" title="Who it applies to" detail={selected.assumes} right="Check applicability" />
                  {selected.weekendNote && <CheckRow state="warn" title="Weekend rule" detail={selected.weekendNote} right="Date adjusted" />}
                  <CheckRow state="todo" title="Professional confirmation" detail="Verify with a qualified professional before relying on the date" right="Your step" />
                </Checklist>
              </div>

              <Callout title="General statutory deadlines">{data.disclaimer} Verify with a qualified professional before relying on a date.</Callout>

              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <a href={selected.source} target="_blank" rel="noreferrer"
                  className="inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg border border-accent bg-accent px-3 text-xs font-bold text-white transition hover:brightness-95">
                  <ExternalLink size={13} /> Open official source
                </a>
                <Btn onClick={() => downloadIcs([selected])}><CalendarPlus size={13} /> Add this date to calendar</Btn>
              </div>
              <ControlNote><b className="text-ink">Scope:</b> rule {selected.rule}. Dates come from the published statutory rule; holidays, extensions and your own filing frequency can change them.</ControlNote>
            </Inspector>
          )}
        </div>
      )}

      <InfoCards items={[
        { icon: Landmark, title: "Official sources only", text: "Every deadline links to the tax authority page it comes from, so the date can be checked against the source before anyone relies on it." },
        { icon: Scale, title: "Weekend and holiday rules", text: "Where an authority moves a deadline that falls on a weekend, the rule is shown with the date. Public holidays and extensions still need checking." },
        { icon: ShieldCheck, title: "Not filing advice", text: "These are general statutory deadlines, not your organisation's obligations. Confirm applicability and dates with a qualified professional." },
      ]} />
    </WorkflowPage>
  );
}
