"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle, BookmarkCheck, CalendarClock, FilePlus2, FileText, History, Library, Scale, ShieldAlert, ShieldCheck,
  Sparkles, Tag, Tags, Trash2, Users,
} from "lucide-react";
import {
  Badge, Btn, Callout, ControlNote, DateCell, Empty, ErrorNote, FilterTabs, Hero, HeroButton, InfoCards, Inspector, KeyGrid,
  Loading, Panel, PanelLink, RegisterHead, RegisterRow, ScopeBar, SearchField, StatCard, SubTabs, WorkflowPage,
  shortId, type Tone,
} from "@/components/workflow-ui/kit";
import { createDraft, deleteSavedAnswer, getAuthToken, listDrafts, listSavedAnswers, type SavedAnswer } from "@/lib/api";

const RISK_TONE: Record<string, Tone> = { LOW: "ok", MEDIUM: "info", HIGH: "warn", RESTRICTED: "bad" };
const RISK_ORDER = ["LOW", "MEDIUM", "HIGH", "RESTRICTED"];
const isHighRisk = (a: SavedAnswer) => a.risk_level === "HIGH" || a.risk_level === "RESTRICTED";
type Tab = "all" | "high" | "drafted" | "untagged";
type Detail = "snapshot" | "audit";
const TEMPLATE = "md:grid-cols-[minmax(0,2.6fr)_minmax(0,0.8fr)_minmax(0,1fr)_minmax(0,0.6fr)]";
const SAVED_BEFORE = [
  { value: "", label: "Any date" },
  { value: "0", label: "Today" },
  { value: "7", label: "7 days ago" },
  { value: "30", label: "30 days ago" },
];

/** End of the day `daysAgo` days back; answers saved on or before it pass. */
function cutoff(daysAgo: string) {
  const d = new Date();
  d.setDate(d.getDate() - Number(daysAgo));
  d.setHours(23, 59, 59, 999);
  return d.getTime();
}

function auditHref(answer: SavedAnswer) {
  return `/audit-replay?correlation_id=${encodeURIComponent(answer.query_id)}`;
}

/** The left-hand list of tag collections. Each row filters the register. */
function Collections({ answers, active, onChange }: { answers: SavedAnswer[]; active: string; onChange: (tag: string) => void }) {
  const counts = new Map<string, number>();
  answers.forEach((a) => a.tags.forEach((t) => counts.set(t, (counts.get(t) ?? 0) + 1)));
  const rows = [{ tag: "", label: "All answers", count: answers.length },
    ...[...counts.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([tag, count]) => ({ tag, label: tag, count }))];
  return (
    <nav aria-label="Collections" className="min-w-0">
      <p className="mb-1.5 text-[10px] font-bold uppercase tracking-[0.16em] text-muted">Collections</p>
      <ul className="space-y-0.5">
        {rows.map((r) => (
          <li key={r.tag || "all"}>
            <button type="button" onClick={() => onChange(r.tag)} aria-pressed={active === r.tag}
              className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs transition ${active === r.tag
                ? "bg-accent/10 font-bold text-accent-ink" : "font-semibold text-ink hover:bg-soft"}`}>
              {r.tag ? <Tag size={12} className="shrink-0 text-muted" /> : <Library size={12} className="shrink-0 text-muted" />}
              <span className="min-w-0 flex-1 truncate">{r.label}</span>
              <span aria-hidden className="rounded-full bg-chip px-1.5 text-[10px] font-bold text-muted">{r.count}</span>
            </button>
          </li>
        ))}
      </ul>
      {counts.size === 0 && <p className="mt-2 px-2 text-[11px] text-muted">No tags on your saved answers yet.</p>}
    </nav>
  );
}

export default function SavedAnswersPage() {
  const router = useRouter();
  const [answers, setAnswers] = useState<SavedAnswer[]>([]);
  const [drafted, setDrafted] = useState<Set<string> | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [error, setError] = useState("");
  const [creatingDraftId, setCreatingDraftId] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<Tab>("all");
  const [risk, setRisk] = useState("");
  const [tag, setTag] = useState("");
  const [savedBefore, setSavedBefore] = useState("");
  const [detail, setDetail] = useState<Detail>("snapshot");

  useEffect(() => {
    const token = getAuthToken();
    listSavedAnswers(token)
      .then(setAnswers)
      .catch(() => { setLoadFailed(true); setError("Could not load saved answers from the server."); })
      .finally(() => setLoading(false));
    listDrafts(token)
      .then((drafts) => setDrafted(new Set(drafts.map((d) => d.saved_answer_id).filter((id): id is string => !!id))))
      .catch(() => setDrafted(null));
  }, []);

  async function handleDelete(id: string) {
    setRemovingId(id);
    try {
      await deleteSavedAnswer(getAuthToken(), id);
      setAnswers((prev) => prev.filter((a) => a.id !== id));
      if (selectedId === id) setSelectedId(null);
    } catch {
      setError("Could not delete this saved answer.");
    } finally {
      setRemovingId(null);
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

  const hasDraft = (a: SavedAnswer) => !!drafted?.has(a.id);
  const needle = query.trim().toLowerCase();
  const before = savedBefore ? cutoff(savedBefore) : null;
  const scoped = answers.filter((a) => (!risk || a.risk_level === risk) && (!tag || a.tags.includes(tag))
    && (before === null || new Date(a.created_at).getTime() <= before));
  const inTab = (a: SavedAnswer) => tab === "all" || (tab === "high" ? isHighRisk(a) : tab === "drafted" ? hasDraft(a) : a.tags.length === 0);
  const visible = scoped.filter((a) => inTab(a) && (!needle
    || [a.query_text, a.answer_text, a.query_id, shortId("KRT", a.id), ...a.tags].some((s) => s.toLowerCase().includes(needle))));
  const selected = visible.find((a) => a.id === selectedId) ?? visible[0] ?? null;
  const risks = [...new Set(answers.map((a) => a.risk_level))].sort((a, b) => RISK_ORDER.indexOf(a) - RISK_ORDER.indexOf(b));
  const tags = [...new Set(answers.flatMap((a) => a.tags))].sort();

  return (
    <WorkflowPage section="Kriton Workspace" title="Saved Answers"
      subtitle="Your governed research library · Retrieve, validate, and reuse answers with professional accountability.">
      <ScopeBar items={[
        { icon: ShieldAlert, label: "Risk level", value: risk, onChange: setRisk,
          options: [{ value: "", label: "All risk levels" }, ...risks.map((r) => ({ value: r, label: r }))] },
        { icon: Tags, label: "Tag", value: tag, onChange: setTag,
          options: [{ value: "", label: "All tags" }, ...tags.map((t) => ({ value: t, label: t }))] },
        { icon: CalendarClock, label: "Saved on or before", value: savedBefore, onChange: setSavedBefore, options: SAVED_BEFORE },
      ]} />

      <Hero icon={BookmarkCheck} eyebrow="Kriton research library · Source-governed" title="Research you can trace. Knowledge you can review."
        subtitle="Saved answers are historical snapshots. Revalidate sources and context before professional reuse."
        actions={<HeroButton primary href="/ask-kriton"><Sparkles size={13} /> New research</HeroButton>} />

      {error && <ErrorNote message={error} />}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard icon={BookmarkCheck} tone="info" value={answers.length} label="Saved answers" hint="In your research library" />
        <StatCard icon={AlertTriangle} tone="bad" value={answers.filter(isHighRisk).length} label="High or restricted risk" hint="Check before reuse" />
        <StatCard icon={FilePlus2} tone="ok" value={drafted ? answers.filter(hasDraft).length : "—"} label="Turned into drafts"
          hint={drafted ? "A draft was created from it" : "Drafts could not be loaded"} />
        <StatCard icon={Tags} tone="neutral" value={answers.filter((a) => a.tags.length > 0).length} label="Tagged" hint="Filed under at least one tag" />
      </div>

      {loading ? <Loading>Loading saved answers…</Loading> : loadFailed ? null : answers.length === 0 ? (
        <Panel title="Research records">
          <Empty icon={BookmarkCheck} title="Nothing saved yet">
            From Ask Kriton, click <span className="font-medium text-ink">Save answer</span> on any composed response to keep it here.
          </Empty>
        </Panel>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
          <div className="min-w-0 space-y-4">
            <Panel title="Research records" subtitle="Answers saved from Ask Kriton, with their risk level and reuse status"
              footer={<span>{visible.length} of {answers.length} saved answers shown</span>}>
              <div className="mb-3 flex gap-2">
                <SearchField value={query} onChange={setQuery} placeholder="Search question, answer text, tag or reference…" label="Search saved answers" />
              </div>
              <FilterTabs label="Filter saved answers" active={tab} onChange={setTab} tabs={[
                { key: "all", label: "All answers", count: scoped.length },
                { key: "high", label: "High risk", count: scoped.filter(isHighRisk).length },
                { key: "drafted", label: "Used in drafts", count: scoped.filter(hasDraft).length },
                { key: "untagged", label: "Untagged", count: scoped.filter((a) => a.tags.length === 0).length },
              ]} />

              <div className="mt-3 grid gap-4 md:grid-cols-[minmax(0,180px)_minmax(0,1fr)]">
                <Collections answers={answers} active={tag} onChange={setTag} />
                {visible.length === 0 ? (
                  <Empty icon={Library} title="No saved answers match">Change the scope, collection, tab or search.</Empty>
                ) : (
                  <div className="min-w-0 overflow-hidden rounded-lg border border-line">
                    <RegisterHead template={TEMPLATE} columns={["Answer / reference", "Risk", "Reuse status", "Saved"]} />
                    {visible.map((a) => (
                      <RegisterRow key={a.id} template={TEMPLATE} selected={selected?.id === a.id}
                        onClick={() => { setSelectedId(a.id); setDetail("snapshot"); }}
                        icon={FileText} tone={RISK_TONE[a.risk_level] ?? "neutral"}
                        title={a.query_text} subtitle={`${shortId("KRT", a.id)} · saved ${new Date(a.created_at).toLocaleDateString()}`}
                        cells={[
                          <Badge key="r" tone={RISK_TONE[a.risk_level] ?? "neutral"}>{a.risk_level}</Badge>,
                          hasDraft(a) ? <Badge key="s" tone="ok">Draft created</Badge> : <Badge key="s">Snapshot</Badge>,
                          <DateCell key="d" iso={a.created_at} />,
                        ]} />
                    ))}
                  </div>
                )}
              </div>
            </Panel>

            <Callout tone="warn" title="Reuse safeguards apply to every saved answer">
              A prior saved status does not establish current source validity. Standards, guidance and the facts of the matter may
              have changed since the answer was saved, so recheck its sources before relying on it.
            </Callout>
          </div>

          {!selected ? (
            <section className="rounded-xl border border-line bg-panel p-4 shadow-[0_4px_14px_rgba(13,34,64,0.05)]" aria-label="Research snapshot inspector">
              <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted">Selected research snapshot</p>
              <Empty icon={Library} title="No answer selected">Change the filters to show a saved answer.</Empty>
            </section>
          ) : (
            <Inspector eyebrow={`Selected research snapshot · ${shortId("KRT", selected.id)}`} title={selected.query_text}
              badges={<>
                <Badge tone="info">Saved snapshot</Badge>
                <Badge tone={RISK_TONE[selected.risk_level] ?? "neutral"}>{selected.risk_level}</Badge>
                {hasDraft(selected) && <Badge tone="ok">Draft created</Badge>}
              </>}>
              <KeyGrid items={[
                ["Risk level", selected.risk_level],
                ["Saved", new Date(selected.created_at).toLocaleString()],
                ["Tags", selected.tags.length ? selected.tags.join(", ") : "None"],
                ["Used in drafts", drafted ? (hasDraft(selected) ? "Yes" : "No") : "—"],
              ]} />

              <SubTabs label="Snapshot details" active={detail} onChange={setDetail} tabs={[
                { key: "snapshot", label: "Answer snapshot" },
                { key: "audit", label: "Audit trail" },
              ]} />
              {detail === "snapshot" ? (
                <div className="max-h-80 overflow-y-auto rounded-lg border border-line bg-soft/40 p-3">
                  <p className="whitespace-pre-line text-xs leading-5 text-ink">{selected.answer_text}</p>
                </div>
              ) : (
                <div className="space-y-2 rounded-lg border border-line bg-soft/40 p-3 text-xs text-ink">
                  <p>The audit trail replays the events recorded for the original question.</p>
                  <p className="break-all text-[11px] text-muted">Query ID: {selected.query_id}</p>
                  <PanelLink href={auditHref(selected)}>View audit trail</PanelLink>
                </div>
              )}

              <Callout tone="info" title="Source provenance preserved, not freshly verified">
                The answer is kept exactly as it was saved. Its sources have not been checked again since.
              </Callout>
              <Callout tone="warn" title="Professional reliance gate">
                This saved answer is not a live, current, or approved opinion. Recheck sources and context before relying on it.
              </Callout>

              <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                <Btn variant="primary" onClick={() => void handleCreateDraft(selected)} busy={creatingDraftId === selected.id}>
                  <FilePlus2 size={13} /> {creatingDraftId === selected.id ? "Creating…" : "Create draft"}
                </Btn>
                <Link href={auditHref(selected)}
                  className="inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg border border-line bg-panel px-3 text-xs font-bold text-ink transition hover:bg-soft">
                  <History size={13} /> View audit trail
                </Link>
                <Btn variant="danger" onClick={() => void handleDelete(selected.id)} busy={removingId === selected.id}>
                  <Trash2 size={13} /> Remove
                </Btn>
              </div>
              <ControlNote><b className="text-ink">Reuse control:</b> creating a draft copies this answer into Drafts &amp; Reports for editing; the saved snapshot itself is not changed.</ControlNote>
            </Inspector>
          )}
        </div>
      )}

      <InfoCards items={[
        { icon: Scale, title: "Authority & effective-date controls", text: "A saved answer reflects the sources available when it was composed; it is not updated when standards or guidance change." },
        { icon: Users, title: "Review & permission boundaries", text: "Saving an answer does not approve it. Professional review happens through drafts, workpapers and review tasks." },
        { icon: ShieldCheck, title: "Replayable research history", text: "Each saved answer keeps the ID of its original question, so the audit trail link replays that question's recorded events." },
      ]} />
    </WorkflowPage>
  );
}
