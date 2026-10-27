"use client";

import { useEffect, useState } from "react";
import {
  Badge, Btn, Callout, CheckRow, Checklist, ControlNote, DateCell, KeyGrid, Panel, inputClass, shortId, type CheckState, type Tone,
} from "@/components/workflow-ui/kit";
import {
  approveResolution, listResolutions, previewResolution, recordJudgment, rejectResolution, releaseCheck, requestReview,
  revokeResolution, saveResolution, type EntityFactsIn, type ReleaseCheck, type ResolutionResult, type StoredResolution,
} from "@/lib/financial-statements-api";

// Standards applicability resolver — Document 03 (ZL-FSR-ENG-003) screen SR-WF-001, controls 01–08.

const FLAGS: [string, string][] = [
  ["listed", "Listed / traded securities"], ["subsidiary", "Subsidiary of a group"], ["bank", "Bank"],
  ["insurer", "Insurer"], ["charity", "Charity"], ["sec_registrant", "SEC registrant"],
];
const FRAMEWORKS: [string, string][] = [
  ["", "Not yet elected"], ["FRS102", "FRS 102"], ["FRS102_1A", "FRS 102 Section 1A (small)"], ["FRS105", "FRS 105 (micro)"],
  ["FRS101", "FRS 101 (reduced disclosure)"], ["IFRS", "IFRS"], ["IFRS_SMES", "IFRS for SMEs"], ["US_GAAP", "US GAAP"],
];
const EARLY: [string, string][] = [["FRS102_PERIODIC_REVIEW", "FRS 102 Periodic Review 2024"], ["IFRS18", "IFRS 18"],
  ["IFRS_SMES_2025", "IFRS for SMEs third edition"]];
const EVIDENCE: [string, string][] = [["framework_election", "Signed framework election"], ["early_adoption", "Early-adoption decision"],
  ["subsidiary", "Group membership"], ["shareholder_notification", "Shareholder notification (FRS 101)"]];
const CANDIDATE_TONE: Record<string, Tone> = { PERMITTED: "ok", CONDITIONAL: "warn", PROHIBITED: "bad", UNKNOWN: "neutral" };
const STATE_TONE: Record<string, Tone> = { FROZEN: "ok", APPROVED: "ok", INVALIDATED: "neutral", REJECTED: "bad", UNSUPPORTED: "bad" };
const REQUIREMENT_STATE: Record<string, CheckState> = {
  REQUIRED: "todo", CONDITIONAL: "warn", ENCOURAGED: "todo", EXEMPT: "pass", NOT_APPLICABLE: "pass",
};
const EMPTY: EntityFactsIn = {
  entity_name: "", incorporation_jurisdiction: "GB-ENG", legal_form: "private_limited", scope: "individual",
  report_type: "annual", period_start: "", period_end: "", flags: [], current_year: {}, prior_year: {},
  framework_election: "", election_signed_by: "", early_adoption: [], requested_claim: "illustrative",
  parent_framework: "", prior_framework: "", first_time_adoption: false, evidence: {},
};
const words = (s: string) => s.replace(/_/g, " ").toLowerCase();
const list = (s: string) => s.split(",").map((v) => v.trim()).filter(Boolean);

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block text-[11px] font-semibold text-muted">{label}<span className="mt-1 block">{children}</span></label>;
}

function Heading({ children }: { children: React.ReactNode }) {
  return <h3 className="text-[10px] font-bold uppercase tracking-wider text-muted">{children}</h3>;
}

function Year({ title, value, onChange }: { title: string; value: EntityFactsIn["current_year"]; onChange: (v: EntityFactsIn["current_year"]) => void }) {
  return (
    <fieldset className="rounded-lg border border-line p-2">
      <legend className="px-1 text-[10px] font-bold uppercase tracking-wider text-muted">{title}</legend>
      <div className="grid gap-2 sm:grid-cols-3">
        <Field label="Turnover"><input inputMode="decimal" value={value.turnover ?? ""} onChange={(e) => onChange({ ...value, turnover: e.target.value })} className={`${inputClass} text-xs`} /></Field>
        <Field label="Balance sheet total"><input inputMode="decimal" value={value.balance_sheet_total ?? ""} onChange={(e) => onChange({ ...value, balance_sheet_total: e.target.value })} className={`${inputClass} text-xs`} /></Field>
        <Field label="Average employees"><input inputMode="numeric" value={value.employees ?? ""} onChange={(e) => onChange({ ...value, employees: e.target.value === "" ? "" : Number(e.target.value) })} className={`${inputClass} text-xs`} /></Field>
      </div>
    </fieldset>
  );
}

function Cite({ code, result }: { code: string; result: ResolutionResult }) {
  const c = result.citations?.[code];
  if (!c) return <span className="ml-1 text-muted">[{code}]</span>;
  return <a href={c.url} target="_blank" rel="noreferrer" title={`${c.publisher} — ${c.title}`} className="ml-1 text-info underline">[{code}]</a>;
}

function Result({ result }: { result: ResolutionResult }) {
  const tests = result.eligibility?.tests ?? [];
  return (
    <div className="space-y-4">
      {/* 07 Release readiness */}
      <Callout tone={result.blockers.length ? "warn" : "info"} title={result.blockers.length ? `${result.blockers.length} blocker(s) · ${words(result.state)}` : `No blockers · ${words(result.state)}`}>
        {result.blockers.length ? "Each blocker below names its owner and the exact action to clear it." : "Ready for an independent reviewer to approve."}
      </Callout>
      {(result.findings ?? []).length > 0 && (
        <ul className="space-y-1.5">
          {result.findings.map((f) => (
            <li key={f.code} className="rounded-lg border border-line p-2 text-[11px] text-ink">
              <div className="flex flex-wrap items-center gap-1.5"><Badge tone={f.severity === "CRITICAL" ? "bad" : "warn"}>{f.severity}</Badge><b>{words(f.code)}</b><span className="text-muted">owner: {f.owner}</span></div>
              <p className="mt-1">{f.reason}</p>
              <p className="mt-0.5 text-muted">Action: {f.action}</p>
            </li>
          ))}
        </ul>
      )}
      <KeyGrid items={[
        ["Selected framework", result.selected_framework ? words(result.selected_framework) : "None"],
        ["Edition", result.framework_edition ?? "—"], ["Size", words(result.size_class)],
        ["Statutory claim", result.permit_statutory_claim ? "Permitted" : "Not permitted"],
      ]} />
      {result.reasons.PARENT_FRAMEWORK && <p className="text-[11px] text-muted">{result.reasons.PARENT_FRAMEWORK}</p>}

      {/* 08 Allowed output types */}
      {(result.outputs ?? []).length > 0 && (
        <div>
          <Heading>Allowed output types</Heading>
          <Checklist>
            {result.outputs.map((o) => <CheckRow key={o.type} state={o.allowed ? "pass" : "fail"} title={words(o.type)} detail={o.gate} right={o.allowed ? "allowed" : "blocked"} />)}
          </Checklist>
        </div>
      )}

      {/* Quality gates G0–G5 */}
      {(result.gates ?? []).length > 0 && (
        <div>
          <Heading>Quality gates</Heading>
          <Checklist>
            {result.gates.map((g) => <CheckRow key={g.gate} state={g.passed ? "pass" : "fail"} title={`${g.gate} ${g.title}`} detail={g.detail} />)}
          </Checklist>
        </div>
      )}

      {/* 03 Candidate frameworks */}
      <div>
        <Heading>Candidate frameworks</Heading>
        <ul className="mt-1 space-y-1.5">
          {result.candidates.map((c) => (
            <li key={c.framework} className="text-[11px] text-ink">
              <Badge tone={CANDIDATE_TONE[c.status] ?? "neutral"}>{c.status}</Badge> <b>{words(c.framework)}</b> — {c.reason}
              {c.sources.map((s) => <Cite key={s} code={s} result={result} />)}
            </li>
          ))}
        </ul>
      </div>

      {/* Eligibility calculation */}
      {tests.length > 0 && (
        <div>
          <Heading>Size test (two of three, two years)</Heading>
          <p className="mt-1 text-[11px] text-muted">{result.eligibility.band}{result.eligibility.exclusions?.length ? ` · excluded: ${result.eligibility.exclusions.join(", ")}` : ""}</p>
          <table className="mt-1 w-full text-left text-[11px]">
            <thead className="text-muted"><tr><th scope="col" className="py-1">Size</th><th scope="col">Criterion</th><th scope="col">Current</th><th scope="col">Prior</th><th scope="col">Limit</th></tr></thead>
            <tbody>
              {tests.flatMap((t) => t.current_criteria.map((c, i) => (
                <tr key={`${t.size}-${c.criterion}`} className="border-t border-line">
                  <td className="py-1 font-semibold">{i === 0 ? t.size : ""}</td><td>{words(c.criterion)}</td>
                  <td className={c.within === false ? "text-bad" : ""}>{c.value ?? "missing"}</td>
                  <td className={t.prior_criteria[i]?.within === false ? "text-bad" : ""}>{t.prior_criteria[i]?.value ?? "missing"}</td>
                  <td>{c.limit}</td>
                </tr>
              )))}
            </tbody>
          </table>
        </div>
      )}

      {/* 04 Effective-dated rule matrix */}
      {result.rules.length > 0 && (
        <div>
          <Heading>Effective-dated rules (by period start)</Heading>
          <table className="mt-1 w-full text-left text-[11px]">
            <thead className="text-muted"><tr><th scope="col" className="py-1">Rule</th><th scope="col">Outcome</th><th scope="col">Adoption</th><th scope="col">Effective</th></tr></thead>
            <tbody>
              {result.rules.map((r) => (
                <tr key={r.rule_id} className="border-t border-line">
                  <td className="py-1 font-semibold">{r.rule_id}<Cite code={r.source} result={result} /></td><td>{words(r.outcome)}</td>
                  <td>{words(r.adoption ?? "")}{r.endorsement ? <span className="block text-muted">endorsement {words(r.endorsement)}</span> : null}</td>
                  <td>{r.effective}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {result.statements.length > 0 && (
        <div>
          <Heading>Statement set</Heading>
          <Checklist>
            {result.statements.map((s) => (
              <CheckRow key={s.statement} state={REQUIREMENT_STATE[s.requirement] ?? "todo"} title={words(s.statement)}
                detail={s.note || undefined} right={words(s.requirement)} />
            ))}
          </Checklist>
        </div>
      )}

      {(result.explanation ?? []).length > 0 && (
        <div>
          <Heading>In plain words</Heading>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[11px] text-ink">{result.explanation.map((l) => <li key={l}>{l}</li>)}</ul>
        </div>
      )}

      {/* 05 Evidence / source citation list */}
      <div>
        <Heading>Sources and rule pack</Heading>
        <ul className="mt-1 space-y-0.5 text-[11px] text-ink">
          {Object.entries(result.citations ?? {}).map(([code, c]) => (
            <li key={code}><b>[{code}]</b> {c.publisher} — <a href={c.url} target="_blank" rel="noreferrer" className="text-info underline">{c.title}</a>
              <span className="text-muted"> · checked {c.checked} · {c.snapshot ? `snapshot ${c.snapshot}` : "no archived snapshot"}</span></li>
          ))}
        </ul>
        <ControlNote>Rule pack {result.rule_pack.id} v{result.rule_pack.version ?? "—"} · {words(result.rule_pack.status)} · checked {result.rule_pack.checked}
          {result.rule_pack.valid_until ? ` · valid until ${result.rule_pack.valid_until}` : ""} · owner {result.rule_pack.owner ?? "unassigned"}
          {" · "}{shortId("sha256", result.rule_pack.digest.replace("sha256:", ""))}. An unreviewed pack never permits a statutory claim.</ControlNote>
      </div>
    </div>
  );
}

function Judgments({ row, busy, onRecord }: { row: StoredResolution; busy: boolean; onRecord: (key: string, choice: string, reason: string) => void }) {
  const [drafts, setDrafts] = useState<Record<string, { choice: string; reason: string }>>({});
  const items = row.result.pending_judgments ?? [];
  if (!items.length) return null;
  return (
    <div>
      <Heading>Judgments (a reviewer other than the preparer)</Heading>
      <ul className="mt-1 space-y-2">
        {items.map((p) => {
          const done = row.judgments?.[p.key];
          const d = drafts[p.key] ?? { choice: "", reason: "" };
          return (
            <li key={p.key} className="rounded-lg border border-line p-2 text-[11px] text-ink">
              <p className="font-semibold">{p.question}</p>
              {done ? <p className="mt-1 text-muted">Decided: <b>{done.choice}</b> — {done.reason} (by {done.by})</p> : (
                <div className="mt-1.5 grid gap-1.5 sm:grid-cols-[1fr_2fr_auto]">
                  <input aria-label={`Choice for ${p.key}`} placeholder="Choice" value={d.choice} onChange={(e) => setDrafts({ ...drafts, [p.key]: { ...d, choice: e.target.value } })} className={`${inputClass} text-xs`} />
                  <input aria-label={`Reason for ${p.key}`} placeholder="Reason and alternatives considered" value={d.reason} onChange={(e) => setDrafts({ ...drafts, [p.key]: { ...d, reason: e.target.value } })} className={`${inputClass} text-xs`} />
                  <Btn busy={busy} disabled={!d.choice.trim() || !d.reason.trim()} onClick={() => onRecord(p.key, d.choice, d.reason)}>Record</Btn>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function StandardsPanel({ trialBalanceId }: { trialBalanceId?: string }) {
  const [facts, setFacts] = useState<EntityFactsIn>(EMPTY);
  const [perimeter, setPerimeter] = useState("");
  const [questions, setQuestions] = useState("");
  const [preview, setPreview] = useState<ResolutionResult | null>(null);
  const [saved, setSaved] = useState<StoredResolution[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [release, setRelease] = useState<ReleaseCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = <K extends keyof EntityFactsIn>(key: K, value: EntityFactsIn[K]) => setFacts((f) => ({ ...f, [key]: value }));
  const toggle = (key: "flags" | "early_adoption", value: string) =>
    setFacts((f) => ({ ...f, [key]: f[key].includes(value) ? f[key].filter((v) => v !== value) : [...f[key], value] }));
  const payload = (): EntityFactsIn => ({ ...facts, group_perimeter: list(perimeter), policy_questions: list(questions) });
  const current = saved.find((r) => r.id === currentId) ?? null;
  const shown = current?.result ?? preview;

  useEffect(() => { listResolutions().then(setSaved).catch(() => setSaved([])); }, []);

  async function run(call: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await call();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The request failed.");
    } finally {
      setBusy(false);
    }
  }

  async function act(call: () => Promise<StoredResolution>) {
    await run(async () => {
      const row = await call();
      setSaved(await listResolutions());
      setCurrentId(row.id);
      setRelease(null);
      setReason("");
    });
  }

  function edit(row: StoredResolution) {
    setFacts({ ...EMPTY, ...row.facts, evidence: row.facts.evidence ?? {} });
    setPerimeter((row.facts.group_perimeter ?? []).join(", "));
    setQuestions((row.facts.policy_questions ?? []).join(", "));
    setCurrentId(null);
    setPreview(row.result);
  }

  const evidence = facts.evidence ?? {};
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Panel title="Entity and period" subtitle="Framework, edition and exemptions are resolved from these facts — never from currency alone">
        <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); void run(async () => { setCurrentId(null); setPreview(await previewResolution(payload())); }); }}>
          <div className="grid gap-2 sm:grid-cols-2">
            <Field label="Legal entity name"><input value={facts.entity_name} onChange={(e) => set("entity_name", e.target.value)} className={`${inputClass} text-xs`} /></Field>
            <Field label="Registered jurisdiction">
              <select value={facts.incorporation_jurisdiction} onChange={(e) => set("incorporation_jurisdiction", e.target.value)} className={`${inputClass} text-xs`}>
                <option value="">Unknown</option><option value="GB-ENG">England and Wales</option><option value="GB-SCT">Scotland</option>
                <option value="GB-NIR">Northern Ireland</option><option value="IE">Ireland</option><option value="US-DE">United States (Delaware)</option>
                <option value="IN">India</option><option value="AE">United Arab Emirates</option>
              </select>
            </Field>
            <Field label="Legal form">
              <select value={facts.legal_form} onChange={(e) => set("legal_form", e.target.value)} className={`${inputClass} text-xs`}>
                <option value="">Unknown</option><option value="private_limited">Private limited company</option>
                <option value="public_limited">Public limited company</option><option value="llp">LLP</option>
                <option value="corporation">Corporation</option><option value="charity">Charity</option>
              </select>
            </Field>
            <Field label="Scope">
              <select value={facts.scope} onChange={(e) => set("scope", e.target.value as EntityFactsIn["scope"])} className={`${inputClass} text-xs`}>
                <option value="individual">Individual accounts</option><option value="group">Group (consolidated) accounts</option>
              </select>
            </Field>
            <Field label="Period start"><input type="date" value={facts.period_start} onChange={(e) => set("period_start", e.target.value)} className={`${inputClass} text-xs`} /></Field>
            <Field label="Period end"><input type="date" value={facts.period_end} onChange={(e) => set("period_end", e.target.value)} className={`${inputClass} text-xs`} /></Field>
            <Field label="Report type">
              <select value={facts.report_type} onChange={(e) => set("report_type", e.target.value as EntityFactsIn["report_type"])} className={`${inputClass} text-xs`}>
                <option value="annual">Annual</option><option value="interim">Interim</option>
                <option value="management">Management</option><option value="educational">Educational</option>
              </select>
            </Field>
            <Field label="Claim requested">
              <select value={facts.requested_claim} onChange={(e) => set("requested_claim", e.target.value as EntityFactsIn["requested_claim"])} className={`${inputClass} text-xs`}>
                <option value="illustrative">Illustrative draft</option><option value="statutory_ready">Statutory-ready</option>
              </select>
            </Field>
            <Field label="Framework election">
              <select value={facts.framework_election} onChange={(e) => set("framework_election", e.target.value)} className={`${inputClass} text-xs`}>
                {FRAMEWORKS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </Field>
            <Field label="Election signed by"><input value={facts.election_signed_by ?? ""} onChange={(e) => set("election_signed_by", e.target.value)} placeholder="e.g. Board minute 12 March 2026" className={`${inputClass} text-xs`} /></Field>
            <Field label="Prior-period framework">
              <select value={facts.prior_framework ?? ""} onChange={(e) => set("prior_framework", e.target.value)} className={`${inputClass} text-xs`}>
                {FRAMEWORKS.map(([v, l]) => <option key={v} value={v}>{v ? l : "None / same"}</option>)}
              </select>
            </Field>
            <Field label="Parent group framework (context only)">
              <select value={facts.parent_framework ?? ""} onChange={(e) => set("parent_framework", e.target.value)} className={`${inputClass} text-xs`}>
                {FRAMEWORKS.map(([v, l]) => <option key={v} value={v}>{v ? l : "No parent / unknown"}</option>)}
              </select>
            </Field>
          </div>
          {facts.scope === "group" && (
            <Field label="Group perimeter (parent and subsidiaries, comma separated)"><input value={perimeter} onChange={(e) => setPerimeter(e.target.value)} className={`${inputClass} text-xs`} /></Field>
          )}
          <fieldset className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-ink">
            <legend className="text-[11px] font-semibold text-muted">Entity status</legend>
            {FLAGS.map(([v, l]) => <label key={v} className="flex items-center gap-1"><input type="checkbox" checked={facts.flags.includes(v)} onChange={() => toggle("flags", v)} />{l}</label>)}
            <label className="flex items-center gap-1"><input type="checkbox" checked={!!facts.first_time_adoption} onChange={(e) => set("first_time_adoption", e.target.checked)} />First-time adoption</label>
          </fieldset>
          <fieldset className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-ink">
            <legend className="text-[11px] font-semibold text-muted">Early adoption elected</legend>
            {EARLY.map(([v, l]) => <label key={v} className="flex items-center gap-1"><input type="checkbox" checked={facts.early_adoption.includes(v)} onChange={() => toggle("early_adoption", v)} />{l}</label>)}
          </fieldset>
          <Year title="Current year" value={facts.current_year} onChange={(v) => set("current_year", v)} />
          <Year title="Prior year (two-year size test)" value={facts.prior_year} onChange={(v) => set("prior_year", v)} />
          <fieldset className="rounded-lg border border-line p-2">
            <legend className="px-1 text-[10px] font-bold uppercase tracking-wider text-muted">Evidence references</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {EVIDENCE.map(([k, l]) => (
                <Field key={k} label={l}><input value={evidence[k] ?? ""} onChange={(e) => set("evidence", { ...evidence, [k]: e.target.value })} placeholder="Document reference" className={`${inputClass} text-xs`} /></Field>
              ))}
            </div>
          </fieldset>
          <Field label="Open accounting-policy judgments (comma separated)"><input value={questions} onChange={(e) => setQuestions(e.target.value)} placeholder="e.g. lease term, revenue principal or agent" className={`${inputClass} text-xs`} /></Field>
          {error && <p role="alert" className="text-[11px] text-bad">{error}</p>}
          <div className="flex flex-wrap gap-2">
            <Btn type="submit" variant="secondary" busy={busy}>Check applicability</Btn>
            <Btn variant="primary" busy={busy} onClick={() => act(() => saveResolution(payload(), trialBalanceId))}>Save resolution</Btn>
          </div>
        </form>
      </Panel>
      <div className="space-y-4">
        <Panel title={current ? `${current.facts.entity_name || "Unnamed entity"} · revision ${current.revision}` : "Resolution"}
          subtitle={current ? `${words(current.state)}${current.pack_is_current ? "" : " · pinned to an earlier rule pack"}` : "Candidates, effective rules and the statement set they imply"}>
          {shown ? (
            <div className="space-y-4">
              {current && (
                <div className="space-y-3">
                  {/* 06 Save / review / approve */}
                  <div className="flex flex-wrap gap-2">
                    {!["FROZEN", "INVALIDATED", "REJECTED"].includes(current.state) && <>
                      <Btn busy={busy} onClick={() => act(() => requestReview(current.id))}>Request review</Btn>
                      <Btn variant="success" busy={busy} disabled={current.result.blockers.length > 0}
                        title={current.result.blockers.length ? "Resolve the blockers first" : undefined}
                        onClick={() => act(() => approveResolution(current.id))}>Approve</Btn>
                    </>}
                    <Btn variant="quiet" busy={busy} onClick={() => edit(current)}>Edit facts</Btn>
                    <Btn variant="quiet" busy={busy} onClick={() => run(async () => setRelease(await releaseCheck(current.id)))}>Release check</Btn>
                  </div>
                  {!["INVALIDATED", "REJECTED"].includes(current.state) && (
                    <div className="flex flex-wrap gap-2">
                      <input aria-label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder={current.state === "FROZEN" ? "Reason to revoke the approval" : "Reason to reject"} className={`${inputClass} min-w-0 flex-1 text-xs`} />
                      {current.state === "FROZEN"
                        ? <Btn variant="danger" busy={busy} disabled={!reason.trim()} onClick={() => act(() => revokeResolution(current.id, reason))}>Revoke approval</Btn>
                        : <Btn variant="danger" busy={busy} disabled={!reason.trim()} onClick={() => act(() => rejectResolution(current.id, reason))}>Reject</Btn>}
                    </div>
                  )}
                  {release && (
                    <Callout tone={release.statutory_release_allowed ? "ok" : "warn"} title={release.statutory_release_allowed ? "Statutory release allowed" : "Statutory release blocked"}>
                      {release.reasons.map((r) => <span key={r} className="block">{r}</span>)}
                    </Callout>
                  )}
                  {current.state === "FROZEN" && !current.approval_valid && (
                    <Callout tone="bad" title="Approval no longer valid">The approver no longer has access; nothing can be released on this approval.</Callout>
                  )}
                  <Judgments key={current.id} row={current} busy={busy}
                    onRecord={(key, choice, why) => act(() => recordJudgment(current.id, { key, choice, reason: why }))} />
                </div>
              )}
              <Result result={shown} />
              {current && current.history.length > 0 && (
                <div>
                  <Heading>History</Heading>
                  <ol className="mt-1 space-y-1 text-[11px] text-ink">
                    {current.history.map((h, i) => (
                      <li key={i} className="flex flex-wrap gap-2"><DateCell iso={h.at} /><span className="font-semibold">{words(h.action)}</span><span className="text-muted">by {h.actor_id} · {words(h.state)}</span></li>
                    ))}
                  </ol>
                </div>
              )}
            </div>
          ) : <p className="text-xs text-muted">Enter the facts and check applicability.</p>}
        </Panel>
        <Panel title="Saved resolutions" subtitle="Changing a fact creates a new revision; judgments and approval need a different person">
          {saved.length === 0 ? <p className="text-xs text-muted">None saved yet.</p> : (
            <ul className="space-y-2 text-[11px]">
              {saved.map((r) => (
                <li key={r.id}>
                  <button type="button" onClick={() => { setCurrentId(r.id); setRelease(null); setReason(""); }}
                    className={`w-full rounded-lg border p-2 text-left ${r.id === currentId ? "border-accent bg-accent/5" : "border-line"}`}>
                    <span className="flex flex-wrap items-center gap-1.5">
                      <Badge tone={STATE_TONE[r.state] ?? "warn"}>{r.state.replace(/_/g, " ")}</Badge>
                      <b>{r.facts.entity_name || "Unnamed entity"}</b><span className="text-muted">rev {r.revision} · {r.result.selected_framework ?? "no framework"} · {r.result.blockers.length} blocker(s)</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}
