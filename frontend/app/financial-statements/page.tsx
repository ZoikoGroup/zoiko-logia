"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Download, FileSpreadsheet, GitBranch, Upload } from "lucide-react";
import {
  Badge, Btn, Callout, CheckRow, Checklist, ControlNote, DateCell, Empty, ErrorNote, KeyGrid, Loading, Panel,
  RegisterHead, RegisterRow, Stack, SubTabs, WorkflowPage, inputClass, shortId, type CheckState, type Tone,
} from "@/components/workflow-ui/kit";
import { StandardsPanel } from "@/components/financial-statements/StandardsPanel";
import { StatementsPanel } from "@/components/financial-statements/StatementsPanel";
import {
  addSupporting, approveSnapshot, decideMapping, downloadOriginal, getCatalogue, getLineage, getTrialBalance,
  listTrialBalances, proposeJournal, reviewJournal, uploadTrialBalance,
  type Catalogue, type Finding, type Lineage, type Mapping, type TrialBalance, type TrialBalanceSummary,
} from "@/lib/financial-statements-api";

// Trial-balance intake — Document 04 (ZL-FSR-ENG-004) screen SD-WF-001.

const STATE: Record<string, { tone: Tone; label: string; text: string }> = {
  REJECTED: { tone: "bad", label: "Rejected", text: "The file was not accepted. Upload a corrected .xlsx or .csv." },
  RECONCILIATION_FAILED: { tone: "bad", label: "Hard stops open", text: "Resolve every hard stop before mapping can be approved." },
  MAPPING_REVIEW: { tone: "warn", label: "Mapping review", text: "Every account needs a reviewer-approved statement line." },
  ADJUSTMENT_PENDING: { tone: "warn", label: "Journal review", text: "Proposed journals are waiting for an independent reviewer." },
  VALIDATED_DRAFT: { tone: "info", label: "Ready for approval", text: "All checks pass. An approver other than the uploader can approve the snapshot." },
  APPROVED_SNAPSHOT: { tone: "ok", label: "Approved snapshot", text: "Frozen and fingerprinted. Any change supersedes this approval." },
  SUPERSEDED: { tone: "neutral", label: "Superseded", text: "A newer version replaces this upload; it is kept for the record." },
};
const MAPPING_TONE: Record<string, Tone> = { SUGGESTED: "info", NEEDS_EVIDENCE: "warn", UNMAPPED: "bad", APPROVED: "ok", REJECTED: "bad" };
const SEVERITY: Record<string, CheckState> = { HARD_STOP: "fail", REVIEW: "warn", INFO: "pass" };
const GRID = "md:grid-cols-[minmax(0,1.6fr)_minmax(0,0.8fr)_minmax(0,0.8fr)_minmax(0,0.6fr)]";

function money(text: string | undefined | null) {
  if (text === undefined || text === null || text === "") return "—";
  const value = Number(text);
  return Number.isFinite(value) ? value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : text;
}

function FindingsList({ findings }: { findings: Finding[] }) {
  if (!findings.length) return <p className="text-xs text-muted">No findings.</p>;
  const order = { HARD_STOP: 0, REVIEW: 1, INFO: 2 } as const;
  return (
    <Checklist>
      {[...findings].sort((a, b) => order[a.severity] - order[b.severity]).map((f, i) => (
        <CheckRow key={`${f.code}-${i}`} state={SEVERITY[f.severity]} title={`${f.code.replace(/_/g, " ")} · ${f.severity.replace("_", " ")}`}
          detail={<>{f.message}{f.refs.length ? <span className="block text-[10px] text-muted">Source: {f.refs.slice(0, 6).join(", ")}</span> : null}</>}
          right={f.rule} />
      ))}
    </Checklist>
  );
}

function MappingRow({ m, lines, busy, onDecide, onTrace }: {
  m: Mapping; lines: Catalogue["lines"]; busy: boolean;
  onDecide: (m: Mapping, body: Parameters<typeof decideMapping>[2]) => void; onTrace: (m: Mapping) => void;
}) {
  const [line, setLine] = useState(m.line_id ?? m.candidates[0]?.line_id ?? "");
  const [evidence, setEvidence] = useState(m.evidence_ref);
  const needsEvidence = m.status === "NEEDS_EVIDENCE" || (m.status === "REJECTED" && !!m.evidence_required);
  const choices = m.candidates.length ? m.candidates : lines;
  return (
    <li className="border-b border-line px-3 py-3 last:border-b-0">
      <div className={`grid gap-2 md:items-center ${GRID}`}>
        <Stack main={m.account_name} sub={m.source ? `Source ${m.source}` : undefined} />
        <span className="text-xs font-semibold tabular-nums text-ink">{money(m.balance)}</span>
        <span><Badge tone={MAPPING_TONE[m.status] ?? "neutral"}>{m.status.replace("_", " ")}</Badge></span>
        <span className="flex justify-start md:justify-end"><Btn variant="quiet" onClick={() => onTrace(m)} label={`Trace ${m.account_name}`}>Trace</Btn></span>
      </div>
      <p className="mt-1 text-[11px] text-muted">
        {m.status === "APPROVED"
          ? <>Approved: {m.allocations.length ? m.allocations.map((a) => `${a.line_id} ${money(a.amount)}`).join(" + ") : m.line_label}{m.evidence_ref ? ` · evidence ${m.evidence_ref}` : ""}</>
          : m.status === "NEEDS_EVIDENCE" ? <>Needs evidence: {m.evidence_required}</> : <>{m.line_label ? `Suggested: ${m.line_label}. ` : ""}{m.basis}</>}
      </p>
      {m.status !== "APPROVED" && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor={`line-${m.id}`}>Statement line for {m.account_name}</label>
          <select id={`line-${m.id}`} value={line} onChange={(e) => setLine(e.target.value)} className={`${inputClass} max-w-xs py-1.5 text-xs`}>
            <option value="">Choose a statement line…</option>
            {choices.map((c) => <option key={c.line_id} value={c.line_id}>{c.label}</option>)}
          </select>
          {needsEvidence && (
            <input aria-label={`Evidence reference for ${m.account_name}`} value={evidence} onChange={(e) => setEvidence(e.target.value)}
              placeholder="Evidence reference (invoice, cost centre…)" className={`${inputClass} max-w-xs py-1.5 text-xs`} />
          )}
          <Btn variant="success" busy={busy} disabled={!line || (needsEvidence && !evidence.trim())}
            onClick={() => onDecide(m, { action: "approve", line_id: line, evidence_ref: evidence.trim() })}>Approve</Btn>
          <Btn variant="danger" busy={busy} onClick={() => onDecide(m, { action: "reject", reason: "Reviewer rejected the suggestion" })}>Reject</Btn>
        </div>
      )}
    </li>
  );
}

function JournalForm({ catalogue, busy, onPropose }: {
  catalogue: Catalogue; busy: boolean; onPropose: (body: Parameters<typeof proposeJournal>[1]) => void;
}) {
  const blank = { line_id: "", debit: "", credit: "" };
  const [kind, setKind] = useState("RECLASSIFICATION");
  const [type, setType] = useState("PRESENTATION");
  const [reason, setReason] = useState("");
  const [evidence, setEvidence] = useState("");
  const [rows, setRows] = useState([{ ...blank }, { ...blank }]);
  const set = (i: number, key: keyof typeof blank, value: string) => setRows((r) => r.map((row, n) => (n === i ? { ...row, [key]: value } : row)));
  const debits = rows.reduce((s, r) => s + (Number(r.debit) || 0), 0);
  const credits = rows.reduce((s, r) => s + (Number(r.credit) || 0), 0);
  return (
    <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); onPropose({
      kind, reason, correction_type: type, evidence_refs: evidence ? [evidence] : [],
      lines: rows.filter((r) => r.line_id).map((r) => ({ line_id: r.line_id, debit: r.debit || "0", credit: r.credit || "0" })),
    }); }}>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="text-[11px] font-semibold text-muted">Kind
          <select value={kind} onChange={(e) => { setKind(e.target.value); setType(e.target.value === "RECLASSIFICATION" ? "PRESENTATION" : "CURRENT_PERIOD"); }} className={`${inputClass} mt-1 text-xs`}>
            <option value="RECLASSIFICATION">Reclassification (presentation only)</option>
            <option value="ADJUSTMENT">Adjustment</option>
          </select>
        </label>
        <label className="text-[11px] font-semibold text-muted">Correction type
          <select value={type} onChange={(e) => setType(e.target.value)} disabled={kind === "RECLASSIFICATION"} className={`${inputClass} mt-1 text-xs`}>
            {catalogue.correction_types.map((c) => <option key={c.code} value={c.code}>{c.code.replace(/_/g, " ").toLowerCase()}</option>)}
          </select>
        </label>
      </div>
      <p className="text-[11px] text-muted">{catalogue.correction_types.find((c) => c.code === type)?.treatment}</p>
      <input aria-label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (required)" className={`${inputClass} text-xs`} />
      <input aria-label="Evidence reference" value={evidence} onChange={(e) => setEvidence(e.target.value)} placeholder="Evidence reference" className={`${inputClass} text-xs`} />
      {rows.map((row, i) => (
        <div key={i} className="grid grid-cols-[minmax(0,1fr)_6rem_6rem] gap-2">
          <select aria-label={`Line ${i + 1} statement line`} value={row.line_id} onChange={(e) => set(i, "line_id", e.target.value)} className={`${inputClass} text-xs`}>
            <option value="">Statement line…</option>
            {catalogue.lines.map((l) => <option key={l.line_id} value={l.line_id}>{l.label}</option>)}
          </select>
          <input aria-label={`Line ${i + 1} debit`} inputMode="decimal" value={row.debit} onChange={(e) => set(i, "debit", e.target.value)} placeholder="Debit" className={`${inputClass} text-xs`} />
          <input aria-label={`Line ${i + 1} credit`} inputMode="decimal" value={row.credit} onChange={(e) => set(i, "credit", e.target.value)} placeholder="Credit" className={`${inputClass} text-xs`} />
        </div>
      ))}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Btn variant="quiet" onClick={() => setRows((r) => [...r, { ...blank }])}>+ Add line</Btn>
        <span className={`text-[11px] font-semibold ${debits === credits && debits > 0 ? "text-ok" : "text-accent-ink"}`}>
          Debits {money(String(debits))} · Credits {money(String(credits))}
        </span>
      </div>
      <Btn type="submit" variant="primary" busy={busy} disabled={!reason.trim() || debits !== credits || debits === 0}>Propose journal (not posted)</Btn>
    </form>
  );
}

export default function FinancialStatementsPage() {
  const [list, setList] = useState<TrialBalanceSummary[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [tb, setTb] = useState<TrialBalance | null>(null);
  const [catalogue, setCatalogue] = useState<Catalogue | null>(null);
  const [lineage, setLineage] = useState<Lineage | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [asNewVersion, setAsNewVersion] = useState(false);
  const [supportKind, setSupportKind] = useState("receivables_ageing");
  const [supportFile, setSupportFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"intake" | "standards" | "statements">("intake");

  const refreshList = useCallback(() => listTrialBalances().then(setList).catch((e: Error) => setError(e.message)), []);
  useEffect(() => { void refreshList(); getCatalogue().then(setCatalogue).catch(() => setCatalogue(null)); }, [refreshList]);
  function select(id: string) {
    setSelected(id);
    setLineage(null);
    getTrialBalance(id).then(setTb).catch((e: Error) => setError(e.message));
  }

  async function act(run: () => Promise<TrialBalance>) {
    setBusy(true);
    setError("");
    try {
      const next = await run();
      setTb(next);
      setSelected(next.id);
      void refreshList();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The request failed.");
    } finally {
      setBusy(false);
    }
  }

  const state = tb ? STATE[tb.state] ?? { tone: "neutral" as Tone, label: tb.state, text: "" } : null;
  const hardStops = useMemo(() => tb?.findings.filter((f) => f.severity === "HARD_STOP").length ?? 0, [tb]);
  const open = tb && !["SUPERSEDED", "REJECTED"].includes(tb.state);

  return (
    <WorkflowPage section="Accounting Workflows" title="Financial Statements"
      subtitle="Trial balance intake · source integrity, reconciliation and evidence-based classification (Document 04)."
      note="Kriton proposes; the deterministic engine checks; an independent reviewer approves. Nothing is posted to any ledger.">
      <SubTabs label="Financial statements step" active={tab} onChange={setTab}
        tabs={[{ key: "intake", label: "Trial balance intake" }, { key: "standards", label: "Framework & rules" },
          { key: "statements", label: "Statements" }]} />
      {tab === "statements" ? <StatementsPanel /> : tab === "standards" ? <StandardsPanel trialBalanceId={selected ?? undefined} /> : <>
      {error && <ErrorNote message={error} />}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <div className="space-y-4">
          <Panel title="Upload a trial balance" subtitle=".xlsx or .csv · up to 20 MB · macros are rejected">
            <div className="space-y-2">
              <input aria-label="Trial balance file" type="file" accept=".csv,.xlsx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="block w-full text-xs text-ink" />
              {tb && open && (
                <label className="flex items-center gap-2 text-[11px] text-muted">
                  <input type="checkbox" checked={asNewVersion} onChange={(e) => setAsNewVersion(e.target.checked)} />
                  Corrected version of {tb.filename} (v{tb.version}); the old version is kept
                </label>
              )}
              <Btn variant="primary" busy={busy} disabled={!file} onClick={() => file && act(() => uploadTrialBalance(file, asNewVersion && tb ? tb.id : undefined))}>
                <Upload size={13} /> Upload and check
              </Btn>
            </div>
          </Panel>
          <Panel title="Uploads" subtitle="Each upload is fingerprinted and kept">
            {list === null ? <Loading>Loading uploads…</Loading> : list.length === 0 ? (
              <Empty icon={FileSpreadsheet} title="No trial balances yet">Upload one to start.</Empty>
            ) : (
              <div className="overflow-hidden rounded-lg border border-line">
                {list.map((item) => (
                  <RegisterRow key={item.id} selected={item.id === selected} onClick={() => select(item.id)} icon={FileSpreadsheet}
                    tone={STATE[item.state]?.tone ?? "info"} title={item.filename}
                    subtitle={`v${item.version} · ${STATE[item.state]?.label ?? item.state}${item.hard_stops ? ` · ${item.hard_stops} hard stop(s)` : ""}`}
                    cells={[]} template="" />
                ))}
              </div>
            )}
          </Panel>
        </div>

        <div className="min-w-0 space-y-4">
          {!tb ? (
            <Panel title="No upload selected"><p className="text-xs text-muted">Choose an upload, or upload a trial balance.</p></Panel>
          ) : (
            <>
              <Panel title={tb.filename} subtitle={`Version ${tb.version} · ${tb.kind === "LEDGER" ? "general ledger" : "trial balance"}`}
                actions={<Btn variant="secondary" onClick={() => downloadOriginal(tb.id, tb.filename).catch((e: Error) => setError(e.message))}><Download size={13} /> Original</Btn>}>
                <KeyGrid items={[
                  ["Fingerprint", <span key="h" title={tb.sha256}>{shortId("sha256", tb.sha256)}</span>],
                  ["Uploaded", <DateCell key="d" iso={tb.created_at} />],
                  ["Units", tb.units], ["Sign convention", tb.sign_convention.replace(/_/g, " ").toLowerCase()],
                  ["Period end", tb.period_end ?? "Not stated"],
                  ["Sheets", (tb.sheets.sheets ?? []).join(", ") + ((tb.sheets.hidden_sheets ?? []).length ? ` (hidden: ${(tb.sheets.hidden_sheets ?? []).join(", ")})` : "")],
                ]} />
                {state && (
                  <div className="mt-3">
                    <Callout tone={state.tone === "ok" ? "ok" : state.tone === "bad" ? "bad" : state.tone === "warn" ? "warn" : "info"}
                      title={`${state.label}${hardStops ? ` · ${hardStops} hard stop(s)` : ""}`}>{state.text}</Callout>
                  </div>
                )}
              </Panel>

              <Panel title="Trial balance check" subtitle={tb.integrity.basis ? `Totals of ${tb.integrity.basis}` : undefined}>
                <div className="grid gap-2 sm:grid-cols-3" role="group" aria-label="Debit and credit totals">
                  {([["Debits", tb.integrity.total_debits], ["Credits", tb.integrity.total_credits], ["Difference", tb.integrity.difference]] as const).map(([k, v]) => (
                    <div key={k} className="rounded-lg border border-line bg-soft/60 p-3">
                      <p className="text-[10px] font-bold uppercase tracking-wider text-muted">{k}</p>
                      <p className={`mt-1 text-sm font-bold tabular-nums ${k === "Difference" && v && Number(v) !== 0 ? "text-bad" : "text-ink"}`}>{money(v)}</p>
                    </div>
                  ))}
                </div>
                <ControlNote>{tb.integrity.note ?? "Debits equal credits proves the arithmetic only."}</ControlNote>
              </Panel>

              <Panel title="Findings" subtitle="Hard stops block approval; review items need a reviewer's decision">
                <FindingsList findings={tb.findings} />
              </Panel>

              <Panel title="Account mapping" subtitle={`${tb.mapping_counts.APPROVED ?? 0} of ${tb.mappings.length} approved · suggestions are never final until a reviewer approves them`}>
                {catalogue && tb.mappings.length ? (
                  <div className="overflow-hidden rounded-lg border border-line">
                    <RegisterHead columns={["Account", "Balance (Dr +)", "Status", ""]} template={GRID} />
                    <ul>
                      {tb.mappings.map((m) => (
                        <MappingRow key={m.id} m={m} lines={catalogue.lines} busy={busy || !open}
                          onDecide={(row, body) => act(() => decideMapping(tb.id, row.id, body))}
                          onTrace={(row) => getLineage(tb.id, row.account_key).then(setLineage).catch((e: Error) => setError(e.message))} />
                      ))}
                    </ul>
                  </div>
                ) : <p className="text-xs text-muted">No accounts to map.</p>}
                {lineage && (
                  <div className="mt-3 rounded-lg border border-info/30 bg-info/5 p-3 text-[11px] text-ink" aria-live="polite">
                    <p className="font-bold"><GitBranch size={12} className="mr-1 inline" />Lineage · {lineage.account_name}</p>
                    <p className="mt-1">File {lineage.source_file.filename} v{lineage.source_file.version} ({shortId("sha256", lineage.source_file.sha256)}) →
                      rows {lineage.source_rows.map((r) => String(r.source)).join(", ")} → {lineage.mapping.line_id ?? "no line yet"} ({lineage.mapping.status.toLowerCase()})
                      {lineage.mapping.evidence_ref ? ` · evidence ${lineage.mapping.evidence_ref}` : ""}
                      {lineage.journals.length ? ` · ${lineage.journals.length} journal(s)` : ""}
                      {lineage.snapshot ? ` · snapshot ${lineage.snapshot.status.toLowerCase()}` : ""}</p>
                  </div>
                )}
              </Panel>

              <div className="grid gap-4 xl:grid-cols-2">
                <Panel title="Propose a journal" subtitle="Balanced, with a reason; simulated before review; never posted">
                  {catalogue && open ? <JournalForm catalogue={catalogue} busy={busy} onPropose={(body) => act(() => proposeJournal(tb.id, body))} />
                    : <p className="text-xs text-muted">Not available for this version.</p>}
                  {tb.effect && (
                    <div className="mt-3 rounded-lg border border-line bg-soft/60 p-3 text-[11px]">
                      <p className="font-bold text-ink">Effect of {tb.effect.journal_id}</p>
                      {tb.effect.lines.map((l) => <p key={l.line_id}>{l.label}: {money(l.before)} → {money(l.after)}</p>)}
                      <p className="mt-1">Profit before tax: {money(tb.effect.profit_before_tax_before)} → {money(tb.effect.profit_before_tax_after)}</p>
                    </div>
                  )}
                </Panel>
                <Panel title="Journals" subtitle="A different person must review each proposal">
                  {tb.journals.length === 0 ? <p className="text-xs text-muted">No journals proposed.</p> : (
                    <ul className="space-y-2">
                      {tb.journals.map((j) => (
                        <li key={j.journal_id} className="rounded-lg border border-line p-3 text-[11px]">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <Badge tone={j.review_status === "APPROVED" ? "ok" : j.review_status === "REJECTED" ? "bad" : "warn"}>{j.review_status.replace("_", " ")}</Badge>
                            <Badge tone="neutral">{j.posting_status.replace("_", " ")}</Badge>
                            {j.requires_restatement && <Badge tone="warn">Restates comparatives</Badge>}
                          </div>
                          <p className="mt-1 font-semibold text-ink">{j.reason}</p>
                          <p className="text-muted">{j.treatment}</p>
                          <p className="mt-1 tabular-nums text-ink">{j.lines.map((l) => `${l.line_id} ${Number(l.debit) ? `Dr ${money(l.debit)}` : `Cr ${money(l.credit)}`}`).join(" · ")}</p>
                          {j.review_status === "PENDING_REVIEW" && open && (
                            <div className="mt-2 flex gap-2">
                              <Btn variant="success" busy={busy} onClick={() => act(() => reviewJournal(tb.id, j.journal_id, true))}>Approve</Btn>
                              <Btn variant="danger" busy={busy} onClick={() => act(() => reviewJournal(tb.id, j.journal_id, false))}>Reject</Btn>
                            </div>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </Panel>
              </div>

              <Panel title="Supporting records" subtitle="Agree control accounts to the receivables ageing, bank reconciliation, stock or asset register">
                {catalogue && open && (
                  <div className="mb-3 flex flex-wrap items-center gap-2">
                    <select aria-label="Supporting record type" value={supportKind} onChange={(e) => setSupportKind(e.target.value)} className={`${inputClass} max-w-xs py-1.5 text-xs`}>
                      {catalogue.supporting_kinds.map((k) => <option key={k.code} value={k.code}>{k.code.replace(/_/g, " ")} → {k.label}</option>)}
                    </select>
                    <input aria-label="Supporting record file" type="file" accept=".csv,.xlsx" onChange={(e) => setSupportFile(e.target.files?.[0] ?? null)} className="text-xs" />
                    <Btn busy={busy} disabled={!supportFile} onClick={() => supportFile && act(() => addSupporting(tb.id, supportKind, supportFile))}>Agree</Btn>
                  </div>
                )}
                {tb.supporting.length ? <FindingsList findings={tb.supporting.map((s) => s.finding)} /> : <p className="text-xs text-muted">None added.</p>}
              </Panel>

              <Panel title="Approval" subtitle="The uploader cannot approve; approval freezes and fingerprints the snapshot">
                <Btn variant="primary" busy={busy} disabled={tb.state !== "VALIDATED_DRAFT"} onClick={() => act(() => approveSnapshot(tb.id))}
                  title={tb.state !== "VALIDATED_DRAFT" ? "Available once every check passes and every mapping and journal is approved" : undefined}>
                  Approve snapshot
                </Btn>
                {tb.snapshots.length > 0 && (
                  <ul className="mt-3 space-y-1 text-[11px]">
                    {tb.snapshots.map((s) => (
                      <li key={s.id} className="flex flex-wrap items-center gap-2">
                        <Badge tone={s.status === "APPROVED" ? "ok" : "neutral"}>{s.status}</Badge>
                        <span title={s.content_hash}>{shortId("sha256", s.content_hash.replace("sha256:", ""))}</span>
                        <DateCell iso={s.approved_at} />
                      </li>
                    ))}
                  </ul>
                )}
                <h3 className="mt-4 text-[10px] font-bold uppercase tracking-wider text-muted">History</h3>
                <ol className="mt-1 space-y-1 text-[11px] text-ink">
                  {tb.history.map((h, i) => (
                    <li key={i} className="flex flex-wrap gap-2"><DateCell iso={h.at} /><span className="font-semibold">{h.action.replace(/_/g, " ")}</span><span className="text-muted">by {h.actor_id}</span></li>
                  ))}
                </ol>
                <ControlNote>{tb.status_note}</ControlNote>
              </Panel>
            </>
          )}
        </div>
      </div>
      </>}
    </WorkflowPage>
  );
}
