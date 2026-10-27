"use client";

import { useEffect, useState } from "react";
import { Badge, Btn, Callout, CheckRow, Checklist, ControlNote, DateCell, KeyGrid, Panel, inputClass, shortId, type Tone } from "@/components/workflow-ui/kit";
import {
  attestRun, decideFinding, downloadAssuranceSummary, getLatestAssurance, listPackages, recordMisstatement, releaseRun, runAssurance,
  setMateriality, uploadEvidence, withdrawEvidence, type AssuranceFinding, type AssuranceView, type PackageSummary,
} from "@/lib/financial-statements-api";

// Assurance workbench — Document 07 (ZL-FSR-ENG-007) wireframe QR-001, controls 01–07.

const SEVERITY_TONE: Record<string, Tone> = { BLOCKER: "bad", CRITICAL: "bad", MATERIAL: "warn", REVIEW: "info", ADVISORY: "neutral" };
const GATE_TONE: Record<string, Tone> = { PASS: "ok", FAIL: "bad", CANNOT_VERIFY: "warn", NOT_APPLICABLE: "neutral" };
const DOMAINS: [string, string][] = [["going_concern", "Going concern"], ["subsequent_events", "Events after the period"],
  ["related_parties", "Related parties"], ["revenue", "Revenue"], ["tax", "Tax"], ["cash_flows", "Cash"],
  ["financial_instruments", "Borrowings"], ["impairment", "Impairment"], ["shared_costs", "Shared costs"]];
const DECISIONS: [string, string][] = [["request_evidence", "Request evidence"], ["accept_treatment", "Accept treatment"],
  ["document_na", "Document not applicable"], ["escalate", "Escalate"], ["waive", "Waive (with expiry)"], ["withdraw", "Withdraw finding"]];
const LADDER: [string, string][] = [["preparer", "Preparer"], ["independent_reviewer", "Independent reviewer"], ["officer", "Director / authorised officer"]];
const words = (s: string) => s.replace(/_/g, " ").toLowerCase();

function Heading({ children }: { children: React.ReactNode }) {
  return <h3 className="text-[10px] font-bold uppercase tracking-wider text-muted">{children}</h3>;
}

function DecisionForm({ finding, view, busy, onDecide }: {
  finding: AssuranceFinding; view: AssuranceView; busy: boolean;
  onDecide: (body: Parameters<typeof decideFinding>[1]) => void;
}) {
  const [decision, setDecision] = useState("request_evidence");
  const [rationale, setRationale] = useState("");
  const [citation, setCitation] = useState("");
  const [alternatives, setAlternatives] = useState("");
  const [evidenceId, setEvidenceId] = useState("");
  const [extra, setExtra] = useState({ expires: "", owner: "", due: "" });
  return (
    <form className="mt-2 grid gap-1.5" onSubmit={(e) => {
      e.preventDefault();
      onDecide({ finding_key: finding.key, decision, rationale, citation, alternatives: alternatives.split(";").map((a) => a.trim()).filter(Boolean),
        evidence_id: evidenceId || null, ...extra });
    }}>
      <select aria-label="Decision" value={decision} onChange={(e) => setDecision(e.target.value)} className={`${inputClass} text-xs`}>
        {DECISIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
      <textarea aria-label="Rationale" rows={2} value={rationale} onChange={(e) => setRationale(e.target.value)} placeholder="Rationale (impact by period and statement)" className={`${inputClass} text-xs`} />
      {decision === "accept_treatment" && <>
        <input aria-label="Citation" value={citation} onChange={(e) => setCitation(e.target.value)} placeholder="Authoritative citation (edition and paragraph)" className={`${inputClass} text-xs`} />
        <input aria-label="Alternatives" value={alternatives} onChange={(e) => setAlternatives(e.target.value)} placeholder="Alternatives rejected (separate with ;)" className={`${inputClass} text-xs`} />
      </>}
      {decision === "document_na" && (
        <select aria-label="Evidence" value={evidenceId} onChange={(e) => setEvidenceId(e.target.value)} className={`${inputClass} text-xs`}>
          <option value="">Choose evidence…</option>
          {view.evidence.filter((x) => !x.withdrawn_at).map((x) => <option key={x.id} value={x.id}>{x.filename}</option>)}
        </select>
      )}
      {decision === "waive" && <input aria-label="Expires" type="date" value={extra.expires} onChange={(e) => setExtra({ ...extra, expires: e.target.value })} className={`${inputClass} text-xs`} />}
      {decision === "request_evidence" && <div className="grid grid-cols-2 gap-1.5">
        <input aria-label="Owner" value={extra.owner} onChange={(e) => setExtra({ ...extra, owner: e.target.value })} placeholder="Owner" className={`${inputClass} text-xs`} />
        <input aria-label="Due" type="date" value={extra.due} onChange={(e) => setExtra({ ...extra, due: e.target.value })} className={`${inputClass} text-xs`} />
      </div>}
      <Btn type="submit" busy={busy}>Record decision</Btn>
    </form>
  );
}

export function AssurancePanel() {
  const [list, setList] = useState<PackageSummary[]>([]);
  const [packageId, setPackageId] = useState("");
  const [view, setView] = useState<AssuranceView | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [scopeFilter, setScopeFilter] = useState("all");
  const [file, setFile] = useState<File | null>(null);
  const [domains, setDomains] = useState<string[]>([]);
  const [description, setDescription] = useState("");
  const [mat, setMat] = useState({ overall: "", performance: "", trivial: "", basis: "", qualitative: "" });
  const [mis, setMis] = useState({ amount: "", statement: "", description: "" });
  const [attest, setAttest] = useState({ scope: "", evidence: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { listPackages().then(setList).catch(() => setList([])); }, []);

  async function act(call: () => Promise<AssuranceView | null>) {
    setBusy(true);
    setError("");
    try {
      const next = await call();
      if (next) setView(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The request failed.");
    } finally {
      setBusy(false);
    }
  }
  function choose(id: string) {
    setPackageId(id);
    setView(null);
    setSelected(null);
    if (id) void act(() => getLatestAssurance(id));
  }

  const finding = view?.findings.find((f) => f.key === selected);
  const gates = (view?.result.gates ?? []).filter((g) => scopeFilter === "all" || g.scope === scopeFilter);
  const blockers = view?.open.filter((f) => ["BLOCKER", "CRITICAL"].includes(f.severity)) ?? [];
  const live = view && !view.superseded_by && !view.certificate;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="block min-w-64 text-[11px] font-semibold text-muted">Report package
          <select value={packageId} onChange={(e) => choose(e.target.value)} className={`${inputClass} mt-1 text-xs`}>
            <option value="">Choose…</option>
            {list.filter((p) => p.state !== "SUPERSEDED").map((p) => <option key={p.id} value={p.id}>{p.entity || "Unnamed entity"} · v{p.version}</option>)}
          </select>
        </label>
        <Btn variant="primary" busy={busy} disabled={!packageId} onClick={() => act(() => runAssurance(packageId))}>Run quality gates</Btn>
        {view && <Btn variant="quiet" onClick={() => act(async () => { await downloadAssuranceSummary(view.id); return null; })}>Findings and limitations summary</Btn>}
      </div>
      {error && <p role="alert" className="text-[11px] text-bad">{error}</p>}

      {!view ? <Panel title="Assurance" subtitle="Quality gates, professional review and internal release">
        <p className="text-xs text-muted">{packageId ? "No run yet — run the quality gates." : "Choose a report package."}</p>
      </Panel> : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="min-w-0 space-y-4">
            {/* 01 Reporting header · 02 Package fingerprint */}
            <Panel title={`${view.header.entity || "Entity"} · ${view.header.period_start} – ${view.header.period_end}`}
              subtitle={`${view.header.framework ? words(view.header.framework) : "No framework"} · ${view.header.edition ?? ""} · ${words(view.header.scope || "")}`}>
              <KeyGrid items={[["Run", shortId("run", view.id)], ["Package", `v${view.package_version}`],
                ["Snapshot", shortId("snap", (view.snapshot_hash ?? "").replace("sha256:", ""))],
                ["Rule set", `${view.ruleset.id} · ${words(view.ruleset.status)}`], ["Inputs", shortId("in", view.input_hash.replace("sha256:", ""))],
                ["Statements", view.header.statements.map(words).join(", ")]]} />
            </Panel>

            {/* 03 Hard-stop banner */}
            <div role="status" aria-live="polite">
              <Callout tone={blockers.length ? "bad" : view.open.length ? "warn" : "info"} title={`${words(view.status).toUpperCase()} · ${view.open.length} open finding(s)`}>
                {blockers.length ? blockers.slice(0, 4).map((f) => <span key={f.key} className="block">{f.code.replace(/_/g, " ").toLowerCase()} — {f.action}</span>)
                  : view.superseded_by ? "Superseded by a newer run after an input changed." : "Release actions follow the authorisation ladder."}
              </Callout>
            </div>

            {/* 04 Quality gate matrix */}
            <Panel title="Quality gates" subtitle="Per statement, cross-statement check, disclosure and evidence domain">
              <div className="mb-2 flex flex-wrap gap-1" role="group" aria-label="Gate scope">
                {["all", "package", "statement", "cross-statement", "disclosure", "evidence"].map((s) => (
                  <button key={s} type="button" aria-pressed={scopeFilter === s} onClick={() => setScopeFilter(s)}
                    className={`rounded-md border px-2 py-1 text-[10px] font-bold ${scopeFilter === s ? "border-accent bg-accent/10" : "border-line text-muted"}`}>{s}</button>
                ))}
              </div>
              <table className="w-full text-left text-[11px]">
                <thead className="text-muted"><tr><th scope="col" className="py-1">Gate</th><th scope="col">Status</th><th scope="col">Method / source</th></tr></thead>
                <tbody>{gates.map((g) => (
                  <tr key={g.gate_id} className="border-t border-line"><td className="py-1 font-semibold">{g.title}</td>
                    <td><Badge tone={GATE_TONE[g.status] ?? "neutral"}>{words(g.status)}</Badge></td><td className="text-muted">{g.method} · {g.source}</td></tr>
                ))}</tbody>
              </table>
            </Panel>

            {/* 05 Finding inspector · 06 Evidence / exception decisions */}
            <Panel title="Finding register" subtitle="Nothing leaves the register; decisions are maker-checker and hash-chained">
              <ul className="space-y-1 text-[11px]">
                {view.findings.map((f) => (
                  <li key={f.key}>
                    <button type="button" onClick={() => setSelected(f.key === selected ? null : f.key)}
                      className={`flex w-full flex-wrap items-center gap-1.5 rounded-lg border p-2 text-left ${f.key === selected ? "border-accent" : "border-line"}`}>
                      <Badge tone={SEVERITY_TONE[f.severity]}>{f.severity}</Badge><b>{words(f.code)}</b>
                      <span className="text-muted">{f.source} · {words(f.assertion)} · {words(f.state)}</span>
                    </button>
                    {finding?.key === f.key && (
                      <div className="mt-1 rounded-lg border border-line bg-soft/60 p-2">
                        <p>{f.message}</p>
                        <p className="text-muted">Rule {f.rule}{f.risk_domain ? ` · domain ${words(f.risk_domain)}` : ""}{f.amount ? ` · amount ${f.amount}` : ""}</p>
                        <p className="text-muted">Action: {f.action}</p>
                        {f.waiver && <p className="text-muted">Waived by {f.waiver.by} until {f.waiver.expires}: {f.waiver.justification}</p>}
                        {live && <DecisionForm key={f.key} finding={f} view={view} busy={busy} onDecide={(body) => act(() => decideFinding(view.id, body))} />}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
              {view.closed_findings.length > 0 && <p className="mt-2 text-[11px] text-muted">Closed by re-run: {view.closed_findings.map((c) => c.key).join(", ")}</p>}
            </Panel>

            <Panel title="What was not checked" subtitle="The negative assertion report">
              <div className="space-y-2 text-[11px]">
                {Object.entries(view.result.negative).filter(([, items]) => items.length).map(([k, items]) => (
                  <div key={k}><Heading>{words(k)}</Heading><ul className="mt-0.5 list-disc pl-4 text-ink">{items.map((i) => <li key={i}>{i}</li>)}</ul></div>
                ))}
              </div>
            </Panel>
          </div>

          <aside className="space-y-4">
            {/* 07 Authorisation ladder */}
            <Panel title="Authorisation ladder" subtitle="No silent auto-sign; each role is a different person">
              <Checklist>
                {LADDER.map(([role, label]) => {
                  const a = view.attestations[role];
                  return <CheckRow key={role} state={a ? "pass" : "todo"} title={label}
                    detail={a ? <span>{a.by} · {a.scope} · <DateCell iso={a.at} /> · {a.auth_aal === "aal2" ? "MFA" : "no MFA"}</span> : undefined}
                    right={!a && live ? <Btn busy={busy} disabled={!attest.scope.trim()} onClick={() => act(() => attestRun(view.id, { role, scope: attest.scope, approval_evidence_id: role === "officer" ? attest.evidence || null : null }))}>Attest</Btn> : null} />;
                })}
              </Checklist>
              {live && <div className="mt-2 grid gap-1.5">
                <input aria-label="Scope reviewed" value={attest.scope} onChange={(e) => setAttest({ ...attest, scope: e.target.value })} placeholder="Scope reviewed, in plain terms" className={`${inputClass} text-xs`} />
                <select aria-label="Approval record" value={attest.evidence} onChange={(e) => setAttest({ ...attest, evidence: e.target.value })} className={`${inputClass} text-xs`}>
                  <option value="">Approval record (officer only)…</option>
                  {view.evidence.filter((x) => !x.withdrawn_at).map((x) => <option key={x.id} value={x.id}>{x.filename}</option>)}
                </select>
                <Btn variant="success" busy={busy} disabled={view.status !== "AUTHORIZED"} onClick={() => act(() => releaseRun(view.id))}>Issue internal release</Btn>
              </div>}
              {view.certificate && (
                <Callout tone="ok" title={`Released ${view.certificate.release_id}`}>
                  <span className="block">{view.certificate.wording}</span>
                  <span className="block">{view.certificate.publication_route}</span>
                </Callout>
              )}
            </Panel>

            <Panel title="Claims" subtitle="Only claims whose prerequisites are evidenced">
              <ul className="space-y-1 text-[11px]">
                {view.claims.map((c) => <li key={c.claim}><Badge tone={c.allowed ? "ok" : "neutral"}>{c.allowed ? "allowed" : "not allowed"}</Badge> <b>{words(c.claim)}</b>
                  <span className="block text-muted">{c.allowed ? c.text : c.missing.join("; ")}</span></li>)}
              </ul>
            </Panel>

            <Panel title="Evidence" subtitle={`Scope: ${words(view.result.evidence_scope)}`}>
              <ul className="space-y-1 text-[11px]">
                {view.result.risk_domains.filter((d) => d.applies).map((d) => <li key={d.domain}><Badge tone={d.covered ? "ok" : "warn"}>{d.covered ? "covered" : "needed"}</Badge> {d.title}</li>)}
              </ul>
              <ul className="mt-2 space-y-1 text-[11px]">
                {view.evidence.map((e) => (
                  <li key={e.id} className={e.withdrawn_at ? "text-muted line-through" : "text-ink"}>{e.filename} · {e.domains.map(words).join(", ")}{e.instruction_flag ? " · instruction text ignored" : ""}
                    {!e.withdrawn_at && live && <button type="button" className="ml-1 text-info underline" onClick={() => act(() => withdrawEvidence(e.id, "Withdrawn by reviewer"))}>withdraw</button>}</li>
                ))}
              </ul>
              {live && <form className="mt-2 grid gap-1.5" onSubmit={(e) => { e.preventDefault(); if (file) void act(() => uploadEvidence(view.package_id, file, domains, description)); }}>
                <input aria-label="Evidence file" type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-xs" />
                <fieldset className="flex flex-wrap gap-x-3 gap-y-1 text-[11px]"><legend className="sr-only">Domains</legend>
                  {DOMAINS.map(([v, l]) => <label key={v} className="flex items-center gap-1"><input type="checkbox" checked={domains.includes(v)} onChange={() => setDomains(domains.includes(v) ? domains.filter((d) => d !== v) : [...domains, v])} />{l}</label>)}
                </fieldset>
                <input aria-label="Evidence description" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What it shows" className={`${inputClass} text-xs`} />
                <Btn type="submit" busy={busy} disabled={!file || !domains.length}>Add evidence</Btn>
              </form>}
            </Panel>

            <Panel title="Materiality and misstatements" subtitle="Approved by a technical lead; never netted">
              <p className="text-[11px] text-muted">{view.materiality.overall ? `Overall ${view.materiality.overall} · performance ${view.materiality.performance} · trivial ${view.materiality.trivial} (${view.materiality.basis})` : "Not approved."}</p>
              <p className="text-[11px] text-muted">Uncorrected: gross {view.result.misstatements.gross} · net {view.result.misstatements.net}</p>
              {live && <div className="mt-2 grid gap-1.5">
                <div className="grid grid-cols-3 gap-1">
                  {(["overall", "performance", "trivial"] as const).map((k) => <input key={k} aria-label={k} inputMode="decimal" placeholder={k} value={mat[k]} onChange={(e) => setMat({ ...mat, [k]: e.target.value })} className={`${inputClass} text-xs`} />)}
                </div>
                <input aria-label="Materiality basis" placeholder="Basis (e.g. 1% of revenue)" value={mat.basis} onChange={(e) => setMat({ ...mat, basis: e.target.value })} className={`${inputClass} text-xs`} />
                <Btn busy={busy} onClick={() => act(() => setMateriality(view.package_id, mat))}>Approve materiality</Btn>
                <div className="grid grid-cols-2 gap-1">
                  <input aria-label="Misstatement amount" placeholder="Amount (signed)" value={mis.amount} onChange={(e) => setMis({ ...mis, amount: e.target.value })} className={`${inputClass} text-xs`} />
                  <input aria-label="Misstatement statement" placeholder="Statement" value={mis.statement} onChange={(e) => setMis({ ...mis, statement: e.target.value })} className={`${inputClass} text-xs`} />
                </div>
                <input aria-label="Misstatement description" placeholder="Description" value={mis.description} onChange={(e) => setMis({ ...mis, description: e.target.value })} className={`${inputClass} text-xs`} />
                <Btn busy={busy} onClick={() => act(() => recordMisstatement(view.package_id, mis))}>Record misstatement</Btn>
              </div>}
            </Panel>
            <ControlNote>Internal quality controls are not an audit, a review engagement, an assurance engagement or regulator acceptance.</ControlNote>
          </aside>
        </div>
      )}
    </div>
  );
}
