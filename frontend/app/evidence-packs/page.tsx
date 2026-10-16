"use client";

import { useEffect, useState } from "react";
import {
  CheckCircle2, Download, FileText, Fingerprint, Link2Off, ListChecks,
  MessageSquareText, PackageCheck, ShieldAlert, ShieldCheck,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
  Badge, Btn, Callout, CheckRow, Checklist, ControlNote, DateCell, Empty, ErrorNote, FilterTabs, Hero, InfoCards, Inspector,
  KeyGrid, LifecycleSteps, ListItem, Loading, Panel, PanelLink, Readiness, RegisterHead, ScopeBar, SearchField, Stack,
  StatCard, StatGrid, WorkflowPage, shortId, type CheckState, type Tone,
} from "@/components/workflow-ui/kit";
import { getAuthToken, listDrafts, listSavedAnswers } from "@/lib/api";
import { downloadEvidencePack, type EvidencePackKind } from "@/lib/accounting-workflows-api";

type Item = {
  kind: EvidencePackKind; id: string; title: string; at: string;
  risk?: string; tags?: string[]; queryId?: string; status?: string; savedAnswerId?: string | null;
};
type Tab = "all" | "saved-answer" | "draft" | "final" | "high-risk";

const CONTENTS = [
  ["answer.md / draft.md", "The question and answer as saved, or the draft text"],
  ["sources.md / sources.json", "The web sources and the excerpts the answer was given"],
  ["review.json", "Review cases on the question and the reviewers' decisions"],
  ["feedback.json", "How users rated the answer"],
  ["audit.json", "The question's audit-ledger events with their chain hashes"],
  ["manifest.json", "Who built the pack and when, and a SHA-256 fingerprint of every file"],
];

const TEMPLATE = "md:grid-cols-[minmax(0,2.4fr)_minmax(0,1.1fr)_minmax(0,1fr)_minmax(0,0.7fr)_auto]";
const TILE: Record<Tone, string> = {
  ok: "bg-ok/10 text-ok", warn: "bg-accent/12 text-accent-ink", bad: "bg-bad/10 text-bad",
  info: "bg-info/10 text-info", neutral: "bg-chip text-muted", brand: "bg-accent/12 text-accent-ink",
};
const RISK_ORDER = ["LOW", "MEDIUM", "HIGH", "RESTRICTED"];
const DRAFT_STATUSES = ["Draft", "In Review", "Final"];

const isHighRisk = (i: Item) => i.kind === "saved-answer" && (i.risk === "HIGH" || i.risk === "RESTRICTED");
const riskTone = (risk?: string): Tone => (risk === "LOW" ? "ok" : risk === "MEDIUM" ? "warn" : risk ? "bad" : "neutral");
const statusTone = (status?: string): Tone => (status === "Final" ? "ok" : status === "In Review" ? "info" : "neutral");
const kindLabel = (i: Item) => (i.kind === "draft" ? "Draft" : "Saved answer");

/** One register line: a select button over the record's cells, and its own download button beside it. */
function PackRow({ item, selected, onSelect, linked, busy, disabled, onDownload }: {
  item: Item; selected: boolean; onSelect: () => void; linked: boolean; busy: boolean; disabled: boolean; onDownload: () => void;
}) {
  const Icon: LucideIcon = item.kind === "draft" ? FileText : MessageSquareText;
  const tone: Tone = isHighRisk(item) ? "bad" : item.kind === "draft" ? (item.status === "Final" ? "ok" : "info") : "info";
  return (
    <div className={`grid gap-x-3 gap-y-1.5 border-b border-line px-3 py-3 transition last:border-b-0 hover:bg-soft md:items-center ${TEMPLATE} ${selected ? "bg-accent/5 shadow-[inset_3px_0_0_var(--accent)]" : ""}`}>
      <button type="button" onClick={onSelect} aria-current={selected || undefined}
        className="grid min-w-0 gap-x-3 gap-y-1.5 text-left md:col-span-4 md:grid-cols-subgrid md:items-center">
        <span className="flex min-w-0 items-start gap-3">
          <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg ${TILE[tone]}`}><Icon size={15} /></span>
          <span className="min-w-0">
            <span className="block truncate text-sm font-semibold text-ink">{item.title}</span>
            <span className="mt-0.5 block truncate text-[11px] text-muted">{shortId("EP", item.id)} · {kindLabel(item)}</span>
          </span>
        </span>
        <span className="min-w-0 pl-11 text-xs text-ink md:pl-0">
          {item.kind === "draft"
            ? <Stack main="Draft" sub={linked ? "From a saved answer" : "No linked answer"} subTone={linked ? "muted" : "warn"} />
            : <Stack main="Saved answer" sub={item.tags?.length ? `${item.tags.length} tag${item.tags.length === 1 ? "" : "s"}` : "No tags"} />}
        </span>
        <span className="min-w-0 pl-11 text-xs text-ink md:pl-0">
          {item.kind === "draft"
            ? <Badge tone={statusTone(item.status)}>{item.status}</Badge>
            : <Badge tone={riskTone(item.risk)}>{item.risk} risk</Badge>}
        </span>
        <span className="min-w-0 pl-11 text-xs text-ink md:pl-0"><DateCell iso={item.at} /></span>
      </button>
      <span className="pl-11 md:pl-0">
        <Btn onClick={onDownload} disabled={disabled} busy={busy} label={`Download evidence pack for ${item.title}`}>
          {!busy && <Download size={13} />} Pack
        </Btn>
      </span>
    </div>
  );
}

export default function EvidencePacksPage() {
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");
  const [done, setDone] = useState("");
  const [tab, setTab] = useState<Tab>("all");
  const [risk, setRisk] = useState("");
  const [draftStatus, setDraftStatus] = useState("");
  const [selectedKey, setSelectedKey] = useState("");

  useEffect(() => {
    const token = getAuthToken();
    Promise.all([listSavedAnswers(token), listDrafts(token)])
      .then(([answers, drafts]) => {
        const all: Item[] = [
          ...answers.map((a) => ({ kind: "saved-answer" as const, id: a.id, title: a.query_text, at: a.created_at,
            risk: a.risk_level, tags: a.tags ?? [], queryId: a.query_id })),
          ...drafts.map((d) => ({ kind: "draft" as const, id: d.id, title: d.title, at: d.updated_at,
            status: d.status, savedAnswerId: d.saved_answer_id })),
        ];
        setItems(all.sort((x, y) => y.at.localeCompare(x.at)));
      })
      .catch(() => setError("Could not load your saved answers and drafts."))
      .finally(() => setLoading(false));
  }, []);

  async function download(item: Item) {
    setBusyId(item.id);
    setActionError("");
    setDone("");
    try {
      await downloadEvidencePack(item.kind, item.id);
      setDone(`Evidence pack for "${item.title.slice(0, 60)}" downloaded.`);
    } catch (err) {
      setActionError((err instanceof Error && err.message) || "Could not build the evidence pack.");
    } finally {
      setBusyId(null);
    }
  }

  const keyOf = (i: Item) => `${i.kind}:${i.id}`;
  const answersById = new Map(items.filter((i) => i.kind === "saved-answer").map((i) => [i.id, i]));
  const linkedAnswer = (i: Item) => (i.kind === "draft" && i.savedAnswerId ? answersById.get(i.savedAnswerId) : undefined);

  const scoped = items.filter((i) => (i.kind === "saved-answer" ? !risk || i.risk === risk : !draftStatus || i.status === draftStatus));
  const inTab = (i: Item) => tab === "all" || (tab === "final" ? i.kind === "draft" && i.status === "Final"
    : tab === "high-risk" ? isHighRisk(i) : i.kind === tab);
  const needle = query.trim().toLowerCase();
  const visible = scoped.filter((i) => inTab(i) && (!needle || i.title.toLowerCase().includes(needle)));

  const answersCount = scoped.filter((i) => i.kind === "saved-answer").length;
  const draftsCount = scoped.filter((i) => i.kind === "draft").length;
  const highRisk = scoped.filter(isHighRisk);
  const finals = scoped.filter((i) => i.kind === "draft" && i.status === "Final");
  const riskLevels = [...new Set(items.map((i) => i.risk).filter((r): r is string => !!r))]
    .sort((a, b) => (RISK_ORDER.indexOf(a) + 1 || 99) - (RISK_ORDER.indexOf(b) + 1 || 99));

  const exceptions = [
    ...highRisk.map((i) => ({ i, title: `${i.risk} risk answer`, tone: "bad" as const, badge: "Review before sharing", icon: ShieldAlert })),
    ...scoped.filter((i) => i.kind === "draft" && !linkedAnswer(i)).map((i) => ({ i, title: "Draft without a linked answer", tone: "warn" as const, badge: "No sources", icon: Link2Off })),
    ...scoped.filter((i) => i.kind === "draft" && i.status !== "Final").map((i) => ({ i, title: `Draft is ${i.status}`, tone: "info" as const, badge: "Not Final", icon: FileText })),
  ];

  const selected = visible.find((i) => keyOf(i) === selectedKey) ?? visible[0];
  const selLinked = selected ? linkedAnswer(selected) : undefined;
  const hasQuestion = selected ? (selected.kind === "saved-answer" ? !!selected.queryId : !!selLinked) : false;

  const gate: { title: string; detail: string; state: CheckState }[] = !selected ? [] : selected.kind === "saved-answer" ? [
    { title: "Record on file", detail: "The saved answer is in your workspace", state: "pass" },
    { title: "Linked to Kriton's question", detail: selected.queryId ? "Sources, reviews, feedback and audit events are read from it" : "No question id on this answer", state: selected.queryId ? "pass" : "warn" },
    { title: "Risk level", detail: isHighRisk(selected) ? `${selected.risk} risk: review before sharing` : `${selected.risk} risk`, state: isHighRisk(selected) ? "warn" : "pass" },
  ] : [
    { title: "Record on file", detail: "The draft is in your workspace", state: "pass" },
    { title: "Linked saved answer", detail: selLinked ? `From "${selLinked.title.slice(0, 60)}"` : selected.savedAnswerId ? "The linked answer is no longer among your saved answers" : "Not created from a saved answer", state: selLinked ? "pass" : "warn" },
    { title: "Draft status is Final", detail: `Status: ${selected.status}`, state: selected.status === "Final" ? "pass" : "warn" },
  ];

  const fromQuestion: CheckState = hasQuestion ? "pass" : "todo";
  const requirements: { title: string; detail: string; state: CheckState; right: string }[] = !selected ? [] : [
    { title: selected.kind === "draft" ? "draft.md" : "answer.md", detail: selected.kind === "draft" ? "The draft text and its status" : "The question and answer as saved, with its risk level", state: "pass", right: "Included" },
    ...(selected.kind === "draft" && selLinked ? [{ title: "original-answer.md", detail: "The saved answer this draft was created from", state: "pass" as const, right: "Included" }] : []),
    { title: "sources.md / sources.json", detail: CONTENTS[1][1], state: fromQuestion, right: hasQuestion ? "From the question" : "Empty" },
    { title: "review.json", detail: CONTENTS[2][1], state: fromQuestion, right: hasQuestion ? "From the question" : "Empty" },
    { title: "feedback.json", detail: CONTENTS[3][1], state: fromQuestion, right: hasQuestion ? "From the question" : "Empty" },
    { title: "audit.json", detail: CONTENTS[4][1], state: fromQuestion, right: hasQuestion ? "From the question" : "Empty" },
    { title: "manifest.json", detail: CONTENTS[5][1], state: "pass", right: "Included" },
  ];

  return (
    <WorkflowPage section="Accounting Workflows" title="Evidence Packs"
      subtitle="Collect, verify, review, and release defensible accounting evidence with end-to-end traceability.">
      <ScopeBar items={[
        { icon: ShieldAlert, label: "Risk level (saved answers)", value: risk, onChange: setRisk,
          options: [{ value: "", label: "All risk levels" }, ...riskLevels.map((r) => ({ value: r, label: `${r} risk` }))] },
        { icon: FileText, label: "Draft status", value: draftStatus, onChange: setDraftStatus,
          options: [{ value: "", label: "All draft statuses" }, ...DRAFT_STATUSES.map((s) => ({ value: s, label: s }))] },
      ]} />

      <Hero icon={PackageCheck} eyebrow="Source authority · Evidence integrity · Professional accountability"
        title="Evidence you can explain. Decisions you can trace."
        subtitle="From saved answers and drafts, build verifiable packs without losing the provenance of a single item."
        aside={<LifecycleSteps title="Controlled evidence lifecycle" steps={["Select", "Build", "Fingerprint", "Download"]} />} />

      {error && <ErrorNote message={error} />}

      <StatGrid>
        <StatCard icon={PackageCheck} tone="info" value={answersCount + draftsCount} label="Evidence packs available" hint="Saved answers and drafts" />
        <StatCard icon={MessageSquareText} tone="brand" value={answersCount} label="From saved answers" hint="Question, sources and audit trail" />
        <StatCard icon={FileText} tone="neutral" value={draftsCount} label="From drafts" hint="Draft text plus its linked answer" />
        <StatCard icon={ShieldAlert} tone="bad" value={highRisk.length} label="High-risk answers" hint="Review before sharing" />
        <StatCard icon={CheckCircle2} tone="ok" value={finals.length} label="Final drafts" hint="Status set to Final" />
      </StatGrid>

      {loading ? <Loading>Loading saved answers and drafts…</Loading> : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
          <div className="min-w-0 space-y-4">
            <Panel title="Evidence pack register" subtitle="Packs are built fresh from Kriton's records on each download">
              <FilterTabs label="Filter evidence packs" active={tab} onChange={setTab} tabs={[
                { key: "all", label: "All packs", count: scoped.length },
                { key: "saved-answer", label: "Saved answers", count: answersCount },
                { key: "draft", label: "Drafts", count: draftsCount },
                { key: "final", label: "Final drafts", count: finals.length },
                { key: "high-risk", label: "High risk", count: highRisk.length },
              ]} />
              <div className="my-3 flex gap-2">
                <SearchField value={query} onChange={setQuery} placeholder="Search answers and drafts…" label="Search answers and drafts" />
              </div>
              {actionError && <div className="mb-2"><ErrorNote message={actionError} /></div>}
              {done && <p className="mb-2 rounded-lg border border-ok/30 bg-ok/5 px-3 py-2 text-xs text-ok">{done}</p>}

              {visible.length === 0 ? (
                <Empty icon={PackageCheck} title={items.length ? "Nothing matches" : "No saved answers or drafts yet"}>
                  {items.length ? "Change the scope, tab or search." : "Save an answer or create a draft to build an evidence pack for it."}
                </Empty>
              ) : (
                <div className="overflow-hidden rounded-lg border border-line">
                  <RegisterHead template={TEMPLATE} columns={["Pack / linked work", "Source type", "Risk or status", "Last changed", "Download"]} />
                  {visible.map((item) => (
                    <PackRow key={keyOf(item)} item={item} selected={!!selected && keyOf(selected) === keyOf(item)}
                      onSelect={() => setSelectedKey(keyOf(item))} linked={!!linkedAnswer(item)}
                      busy={busyId === item.id} disabled={busyId !== null} onDownload={() => void download(item)} />
                  ))}
                </div>
              )}
              <p className="mt-2 text-[11px] text-muted">{visible.length} of {items.length} items shown</p>
            </Panel>

            <div className="grid gap-4 md:grid-cols-2">
              <Panel title="What a pack contains">
                <Checklist>{CONTENTS.map(([file, what]) => <CheckRow key={file} state="pass" title={file} detail={what} />)}</Checklist>
              </Panel>
              <Panel title="Priority exceptions">
                {exceptions.length === 0 ? <p className="py-3 text-xs text-muted">No high-risk answers or unfinished drafts.</p> : (
                  <ul>{exceptions.slice(0, 5).map(({ i, title, tone, badge, icon }) => (
                    <ListItem key={`${badge}:${keyOf(i)}`} icon={icon} tone={tone} title={title}
                      detail={`${i.title} · ${shortId("EP", i.id)}`} badge={<Badge tone={tone}>{badge}</Badge>}
                      onClick={() => { setTab("all"); setQuery(""); setSelectedKey(keyOf(i)); }} />
                  ))}</ul>
                )}
              </Panel>
            </div>
          </div>

          {!selected ? (
            <section className="rounded-xl border border-line bg-panel p-4 shadow-[0_4px_14px_rgba(13,34,64,0.05)]" aria-label="Evidence pack inspector">
              <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted">Evidence pack inspector</p>
              <Empty icon={PackageCheck} title="Select an item">Pick a saved answer or draft to see what its pack will hold.</Empty>
            </section>
          ) : (
            <Inspector eyebrow={`Evidence pack inspector · ${shortId("EP", selected.id)}`} title={selected.title}
              badges={<>
                <Badge tone="info">{kindLabel(selected)}</Badge>
                {selected.kind === "draft"
                  ? <Badge tone={statusTone(selected.status)}>{selected.status}</Badge>
                  : <Badge tone={riskTone(selected.risk)}>{selected.risk} risk</Badge>}
              </>}
              description={selected.kind === "draft"
                ? "The draft text, with the sources, reviews, feedback and audit events of the saved answer it came from."
                : "The question and answer as saved, with the sources, reviews, feedback and audit events of its question."}>
              <KeyGrid items={selected.kind === "draft" ? [
                ["Source", "Draft"],
                ["Status", selected.status ?? "—"],
                ["Updated", new Date(selected.at).toLocaleString()],
                ["From a saved answer", selLinked ? "Yes" : selected.savedAnswerId ? "Yes (no longer saved)" : "No"],
              ] : [
                ["Source", "Saved answer"],
                ["Risk level", selected.risk ?? "—"],
                ["Created", new Date(selected.at).toLocaleString()],
                ["Tags", selected.tags?.length ? selected.tags.join(", ") : "None"],
              ]} />

              <Readiness label="Pack readiness" passed={gate.filter((c) => c.state === "pass").length} total={gate.length}
                hint="Readiness is a checklist indicator, not accounting approval." />

              {isHighRisk(selected) ? (
                <Callout tone="bad" title="High-risk answer">Rated {selected.risk} risk. Review the answer and its sources before sharing the pack.</Callout>
              ) : selected.kind === "draft" && !selLinked ? (
                <Callout tone="warn" title="No linked question">This draft is not linked to one of your saved answers, so the pack has no sources, reviews or audit events.</Callout>
              ) : selected.kind === "draft" && selected.status !== "Final" ? (
                <Callout tone="info" title={`Draft is ${selected.status}`}>The pack exports the draft text as it stands now, not a final version.</Callout>
              ) : null}

              <div>
                <p className="mb-1 border-b border-line pb-1.5 text-xs font-bold text-accent-ink">Requirements</p>
                <Checklist>{requirements.map((r) => <CheckRow key={r.title} state={r.state} title={r.title} detail={r.detail} right={r.right} />)}</Checklist>
              </div>

              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <Btn variant="primary" onClick={() => void download(selected)} disabled={busyId !== null} busy={busyId === selected.id}>
                  {busyId !== selected.id && <Download size={13} />} Build &amp; download pack
                </Btn>
                {selected.kind === "saved-answer" && selected.queryId && (
                  <span className="flex items-center justify-center">
                    <PanelLink href={`/audit-replay?correlation_id=${encodeURIComponent(selected.queryId)}`}>Replay the audit trail</PanelLink>
                  </span>
                )}
              </div>
              <ControlNote><b className="text-ink">Integrity control:</b> manifest.json fingerprints every file with SHA-256, so a recipient can check nothing was changed; each download is recorded in the audit log.</ControlNote>
            </Inspector>
          )}
        </div>
      )}

      <InfoCards items={[
        { icon: ListChecks, title: "Versioned evidence manifest", text: "manifest.json lists every file with its size and SHA-256, and who built the pack and when. Packs are not stored; each is rebuilt from the records." },
        { icon: Fingerprint, title: "File digest and provenance chain", text: "audit.json carries the question's audit-ledger events with their payload and chain hashes, so the trail can be checked against the ledger." },
        { icon: ShieldCheck, title: "Reviewer approval + policy gates", text: "review.json carries the review cases opened on the question and the reviewers' decisions and notes." },
      ]} />
    </WorkflowPage>
  );
}
