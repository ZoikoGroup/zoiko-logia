"use client";

import { useEffect, useState } from "react";
import {
  Badge, Btn, Callout, CheckRow, Checklist, ControlNote, KeyGrid, Panel, inputClass, shortId, type CheckState, type Tone,
} from "@/components/workflow-ui/kit";
import {
  approveResolution, listResolutions, previewResolution, saveResolution,
  type EntityFactsIn, type ResolutionResult, type StoredResolution,
} from "@/lib/financial-statements-api";

// Standards applicability resolver — Document 03 (ZL-FSR-ENG-003) screen SR-WF-001.

const FLAGS: [string, string][] = [
  ["listed", "Listed / traded securities"], ["subsidiary", "Subsidiary of a group"], ["bank", "Bank"],
  ["insurer", "Insurer"], ["charity", "Charity"], ["sec_registrant", "SEC registrant"],
];
const ELECTIONS: [string, string][] = [
  ["", "Not yet elected"], ["FRS102", "FRS 102"], ["FRS102_1A", "FRS 102 Section 1A (small)"], ["FRS105", "FRS 105 (micro)"],
  ["FRS101", "FRS 101 (reduced disclosure)"], ["IFRS", "IFRS"], ["US_GAAP", "US GAAP"],
];
const CANDIDATE_TONE: Record<string, Tone> = { PERMITTED: "ok", CONDITIONAL: "warn", PROHIBITED: "bad", UNKNOWN: "neutral" };
const REQUIREMENT_STATE: Record<string, CheckState> = {
  REQUIRED: "todo", CONDITIONAL: "warn", ENCOURAGED: "todo", EXEMPT: "pass", NOT_APPLICABLE: "pass",
};
const EMPTY: EntityFactsIn = {
  entity_name: "", incorporation_jurisdiction: "GB-ENG", legal_form: "private_limited", scope: "individual",
  report_type: "annual", period_start: "", period_end: "", flags: [], current_year: {}, prior_year: {},
  framework_election: "", early_adoption: [], requested_claim: "illustrative",
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block text-[11px] font-semibold text-muted">{label}<span className="mt-1 block">{children}</span></label>;
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

function Result({ result }: { result: ResolutionResult }) {
  return (
    <div className="space-y-3">
      <Callout tone={result.blockers.length ? "warn" : "info"} title={result.blockers.length ? `${result.blockers.length} blocker(s) · ${result.state.replace(/_/g, " ").toLowerCase()}` : `No blockers · ${result.state.replace(/_/g, " ").toLowerCase()}`}>
        {result.blockers.length ? result.blockers.map((b) => <span key={b} className="block"><b>{b.replace(/_/g, " ")}</b>: {result.reasons[b]}</span>) : "Ready for an independent reviewer to approve."}
      </Callout>
      <KeyGrid items={[
        ["Selected framework", result.selected_framework ?? "None"], ["Size", result.size_class.replace(/_/g, " ")],
        ["Statutory claim", result.permit_statutory_claim ? "Permitted" : "Not permitted"],
        ["Exports", result.permitted_exports.join(", ").replace(/_/g, " ").toLowerCase()],
      ]} />
      {result.reasons.SIZE && <p className="text-[11px] text-muted">Size test: {result.reasons.SIZE}</p>}
      <div>
        <h3 className="text-[10px] font-bold uppercase tracking-wider text-muted">Candidate frameworks</h3>
        <ul className="mt-1 space-y-1.5">
          {result.candidates.map((c) => (
            <li key={c.framework} className="text-[11px] text-ink">
              <Badge tone={CANDIDATE_TONE[c.status] ?? "neutral"}>{c.status}</Badge> <b>{c.framework.replace(/_/g, " ")}</b> — {c.reason}
              {c.sources.map((s) => <a key={s} href={s} target="_blank" rel="noreferrer" className="ml-1 text-info underline">source</a>)}
            </li>
          ))}
        </ul>
      </div>
      {result.rules.length > 0 && (
        <div>
          <h3 className="text-[10px] font-bold uppercase tracking-wider text-muted">Effective-dated rules (by period start)</h3>
          <table className="mt-1 w-full text-left text-[11px]">
            <thead className="text-muted"><tr><th scope="col" className="py-1">Rule</th><th scope="col">Outcome</th><th scope="col">Effective</th></tr></thead>
            <tbody>
              {result.rules.map((r) => (
                <tr key={r.rule_id} className="border-t border-line">
                  <td className="py-1 font-semibold">{r.rule_id}</td><td>{r.outcome.replace(/_/g, " ").toLowerCase()}</td>
                  <td><a href={r.source} target="_blank" rel="noreferrer" className="text-info underline">{r.effective}</a></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {result.statements.length > 0 && (
        <div>
          <h3 className="text-[10px] font-bold uppercase tracking-wider text-muted">Statement set</h3>
          <Checklist>
            {result.statements.map((s) => (
              <CheckRow key={s.statement} state={REQUIREMENT_STATE[s.requirement] ?? "todo"} title={s.statement.replace(/_/g, " ")}
                detail={s.note || undefined} right={s.requirement.replace(/_/g, " ").toLowerCase()} />
            ))}
          </Checklist>
        </div>
      )}
      <ControlNote>Rule pack {result.rule_pack.id} · {result.rule_pack.status.replace(/_/g, " ").toLowerCase()} · checked {result.rule_pack.checked}
        {" · "}{shortId("sha256", result.rule_pack.digest.replace("sha256:", ""))}. An unreviewed pack never permits a statutory claim.</ControlNote>
    </div>
  );
}

export function StandardsPanel({ trialBalanceId }: { trialBalanceId?: string }) {
  const [facts, setFacts] = useState<EntityFactsIn>(EMPTY);
  const [preview, setPreview] = useState<ResolutionResult | null>(null);
  const [saved, setSaved] = useState<StoredResolution[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = <K extends keyof EntityFactsIn>(key: K, value: EntityFactsIn[K]) => setFacts((f) => ({ ...f, [key]: value }));
  const toggle = (key: "flags" | "early_adoption", value: string) =>
    setFacts((f) => ({ ...f, [key]: f[key].includes(value) ? f[key].filter((v) => v !== value) : [...f[key], value] }));

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

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Panel title="Entity and period" subtitle="Framework, edition and exemptions are resolved from these facts — never from currency alone">
        <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); void run(async () => setPreview(await previewResolution(facts))); }}>
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
            <Field label="Framework election">
              <select value={facts.framework_election} onChange={(e) => set("framework_election", e.target.value)} className={`${inputClass} text-xs`}>
                {ELECTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </Field>
          </div>
          <fieldset className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-ink">
            <legend className="text-[11px] font-semibold text-muted">Entity status</legend>
            {FLAGS.map(([v, l]) => <label key={v} className="flex items-center gap-1"><input type="checkbox" checked={facts.flags.includes(v)} onChange={() => toggle("flags", v)} />{l}</label>)}
          </fieldset>
          <fieldset className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-ink">
            <legend className="text-[11px] font-semibold text-muted">Early adoption elected</legend>
            <label className="flex items-center gap-1"><input type="checkbox" checked={facts.early_adoption.includes("FRS102_PERIODIC_REVIEW")} onChange={() => toggle("early_adoption", "FRS102_PERIODIC_REVIEW")} />FRS 102 Periodic Review 2024</label>
            <label className="flex items-center gap-1"><input type="checkbox" checked={facts.early_adoption.includes("IFRS18")} onChange={() => toggle("early_adoption", "IFRS18")} />IFRS 18</label>
          </fieldset>
          <Year title="Current year" value={facts.current_year} onChange={(v) => set("current_year", v)} />
          <Year title="Prior year (two-year size test)" value={facts.prior_year} onChange={(v) => set("prior_year", v)} />
          {error && <p role="alert" className="text-[11px] text-bad">{error}</p>}
          <div className="flex flex-wrap gap-2">
            <Btn type="submit" variant="secondary" busy={busy}>Check applicability</Btn>
            <Btn variant="primary" busy={busy} onClick={() => run(async () => {
              const row = await saveResolution(facts, trialBalanceId);
              setPreview(row.result);
              setSaved(await listResolutions());
            })}>Save resolution</Btn>
          </div>
        </form>
      </Panel>
      <div className="space-y-4">
        <Panel title="Resolution" subtitle="Candidates, effective rules and the statement set they imply">
          {preview ? <Result result={preview} /> : <p className="text-xs text-muted">Enter the facts and check applicability.</p>}
        </Panel>
        <Panel title="Saved resolutions" subtitle="Changing a fact creates a new revision; approval needs a different person">
          {saved.length === 0 ? <p className="text-xs text-muted">None saved yet.</p> : (
            <ul className="space-y-2 text-[11px]">
              {saved.map((r) => (
                <li key={r.id} className="rounded-lg border border-line p-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge tone={r.state === "FROZEN" ? "ok" : r.state === "INVALIDATED" ? "neutral" : "warn"}>{r.state.replace(/_/g, " ")}</Badge>
                    <b>{r.facts.entity_name || "Unnamed entity"}</b><span className="text-muted">rev {r.revision} · {r.result.selected_framework ?? "no framework"}</span>
                  </div>
                  {!["FROZEN", "INVALIDATED"].includes(r.state) && (
                    <Btn variant="success" busy={busy} disabled={r.result.blockers.length > 0} className="mt-1.5"
                      title={r.result.blockers.length ? "Resolve the blockers first" : undefined}
                      onClick={() => run(async () => { await approveResolution(r.id); setSaved(await listResolutions()); })}>Approve</Btn>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}
