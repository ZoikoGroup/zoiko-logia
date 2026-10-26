"use client";

import { useEffect, useState } from "react";
import {
  Badge, Btn, Callout, CheckRow, Checklist, ControlNote, DateCell, KeyGrid, Panel, inputClass, shortId, type CheckState, type Tone,
} from "@/components/workflow-ui/kit";
import {
  approveDisclosure, buildPackage, disposeFinding, downloadPackage, getPackage, listPackages, listResolutions, listTrialBalances,
  packageReleaseCheck, signPackage, submitDisclosure, type AssembledStatement, type PackageNote, type PackageReleaseCheck,
  type PackageSummary, type ReportPackage, type StoredResolution, type TrialBalanceSummary,
} from "@/lib/financial-statements-api";

// Statement assembly workspace — Document 05 (ZL-FSR-ENG-005) screen FS-AW-001, callouts 01–08.

const ROLES: [string, string][] = [["preparer", "Preparer"], ["technical_reviewer", "Technical reviewer"],
  ["disclosure_owner", "Disclosure owner"], ["issuer", "Authorised issuer"]];
const SEVERITY_TONE: Record<string, Tone> = { P0: "bad", P1: "warn", P2: "info", P3: "neutral" };
const STATUS_TONE: Record<string, Tone> = { PASS: "ok", FAIL: "bad", EXEMPT: "info", NOT_APPLICABLE: "neutral", NOT_EVALUATED: "warn",
  ASSEMBLED: "ok", BLOCKED: "bad" };
const NOTE_STATE: Record<string, CheckState> = { SUPPORTED: "pass", NOT_APPLICABLE: "pass", EXEMPT: "pass",
  PENDING_APPROVAL: "warn", CONDITIONAL_UNDECIDED: "warn", REQUIRED_MISSING: "fail" };
const words = (s: string) => s.replace(/_/g, " ").toLowerCase();
const money = (v: string | null | undefined) => {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  return Number.isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: 2 }) : v;
};

function Heading({ children }: { children: React.ReactNode }) {
  return <h3 className="text-[10px] font-bold uppercase tracking-wider text-muted">{children}</h3>;
}

function StatementPreview({ statement }: { statement: AssembledStatement }) {
  if (!statement.lines.length) {
    return <p className="text-[11px] text-muted">{statement.note || words(statement.status)}{statement.data_required?.length ? ` Needed: ${statement.data_required.join("; ")}.` : ""}</p>;
  }
  const soce = !!statement.components;
  const prior = statement.lines.some((l) => l.prior !== null);
  return (
    <div>
      {statement.starting_point && <p className="text-[11px] text-muted">Indirect method from {statement.starting_point.toLowerCase()}. {statement.policy}</p>}
      <table className="mt-1 w-full text-left text-[11px]">
        <thead className="text-muted"><tr><th scope="col" className="py-1">Line</th>
          {soce ? <><th scope="col" className="text-right">Share capital</th><th scope="col" className="text-right">Retained earnings</th></> : null}
          <th scope="col" className="text-right">{soce ? "Total" : "Current"}</th>{prior && <th scope="col" className="text-right">Prior</th>}</tr></thead>
        <tbody>
          {statement.lines.map((l) => (
            <tr key={l.line_id} className={`border-t border-line ${l.kind !== "line" ? "font-semibold" : ""}`}>
              <td className="py-1" title={l.concepts.join(", ")}>{l.label}</td>
              {soce ? <><td className="text-right tabular-nums">{money(l.share_capital)}</td><td className="text-right tabular-nums">{money(l.retained_earnings)}</td></> : null}
              <td className="text-right tabular-nums">{money(l.amount)}</td>{prior && <td className="text-right tabular-nums">{money(l.prior)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function NoteRow({ note, busy, onSubmit, onApprove }: {
  note: PackageNote; busy: boolean;
  onSubmit: (body: { decision: string; text: string; evidence_ref: string; rationale: string }) => void; onApprove: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [decision, setDecision] = useState("include");
  const [text, setText] = useState("");
  const [evidence, setEvidence] = useState("");
  const editable = !["NOT_APPLICABLE", "EXEMPT"].includes(note.state) || note.submitted_by;
  return (
    <CheckRow state={NOTE_STATE[note.state] ?? "todo"} title={`${note.requirement_id} ${note.title}`}
      right={<span className="flex items-center gap-1.5">{words(note.state)}
        {note.state === "PENDING_APPROVAL" && <Btn busy={busy} onClick={onApprove}>Approve</Btn>}
        {editable && note.state !== "SUPPORTED" && <Btn variant="quiet" onClick={() => setOpen(!open)}>{open ? "Close" : "Provide"}</Btn>}</span>}
      detail={<span className="block space-y-1">
        <span className="block text-muted">{note.rule} · needs: {note.evidence_needed}</span>
        {note.text && <span className="block text-ink">{note.text}{note.amount ? ` (${money(note.amount)})` : ""}{note.evidence_ref ? ` · evidence ${note.evidence_ref}` : ""}</span>}
        {note.issues.length > 0 && <span className="block text-bad">{note.issues.map(words).join(", ")}</span>}
        {open && (
          <span className="mt-1 grid gap-1.5">
            <select aria-label={`Decision for ${note.requirement_id}`} value={decision} onChange={(e) => setDecision(e.target.value)} className={`${inputClass} text-xs`}>
              <option value="include">Include with evidence</option><option value="not_applicable">Not applicable (with rationale)</option>
              <option value="exempt">Claim an exemption</option>
            </select>
            <textarea aria-label={`Text for ${note.requirement_id}`} value={text} onChange={(e) => setText(e.target.value)} rows={2}
              placeholder={decision === "not_applicable" ? "Why it does not apply" : "Note text, from the evidence only"} className={`${inputClass} text-xs`} />
            <input aria-label={`Evidence for ${note.requirement_id}`} value={evidence} onChange={(e) => setEvidence(e.target.value)} placeholder="Evidence reference" className={`${inputClass} text-xs`} />
            <Btn busy={busy} disabled={!text.trim() && decision !== "exempt"} onClick={() => {
              onSubmit({ decision, text: decision === "not_applicable" ? "" : text, rationale: decision === "not_applicable" ? text : "", evidence_ref: evidence });
              setOpen(false);
            }}>Submit</Btn>
          </span>
        )}
      </span>} />
  );
}

export function StatementsPanel() {
  const [tbs, setTbs] = useState<TrialBalanceSummary[]>([]);
  const [resolutions, setResolutions] = useState<StoredResolution[]>([]);
  const [packages, setPackages] = useState<PackageSummary[]>([]);
  const [tbId, setTbId] = useState("");
  const [priorId, setPriorId] = useState("");
  const [resolutionId, setResolutionId] = useState("");
  const [schedules, setSchedules] = useState<Record<string, string>>({});
  const [pkg, setPkg] = useState<ReportPackage | null>(null);
  const [statementId, setStatementId] = useState<string | null>(null);
  const [assertionId, setAssertionId] = useState<string | null>(null);
  const [disposal, setDisposal] = useState<Record<string, string>>({});
  const [release, setRelease] = useState<PackageReleaseCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    listTrialBalances().then(setTbs).catch(() => setTbs([]));
    listResolutions().then(setResolutions).catch(() => setResolutions([]));
    listPackages().then(setPackages).catch(() => setPackages([]));
  }, []);

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
  async function show(call: () => Promise<ReportPackage>) {
    await run(async () => {
      const next = await call();
      setPkg(next);
      setRelease(null);
      setPackages(await listPackages());
    });
  }
  const set = (key: string, value: string) => setSchedules((s) => ({ ...s, [key]: value }));
  const approved = tbs.filter((t) => t.state === "APPROVED_SNAPSHOT");
  const result = pkg?.result;
  const statement = result?.statements.find((s) => s.statement_id === statementId) ?? result?.statements[0];
  const cashFields = result?.cash_flow_data_fields ?? {};
  const open = pkg && !["SUPERSEDED", "INVALIDATED"].includes(pkg.state);

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,24rem)_minmax(0,1fr)]">
      <div className="space-y-4">
        {/* 01 Statement assembly command · 02 profile */}
        <Panel title="Assemble statements" subtitle="From an approved trial-balance snapshot and a frozen framework resolution">
          <form className="space-y-2" onSubmit={(e) => {
            e.preventDefault();
            void show(() => buildPackage({ trial_balance_id: tbId, resolution_id: resolutionId || null, prior_trial_balance_id: priorId || null, schedules }));
          }}>
            <label className="block text-[11px] font-semibold text-muted">Approved trial balance
              <select required value={tbId} onChange={(e) => setTbId(e.target.value)} className={`${inputClass} mt-1 text-xs`}>
                <option value="">Choose…</option>
                {approved.map((t) => <option key={t.id} value={t.id}>{t.filename} · v{t.version}</option>)}
              </select>
            </label>
            <label className="block text-[11px] font-semibold text-muted">Framework resolution (Document 03)
              <select value={resolutionId} onChange={(e) => setResolutionId(e.target.value)} className={`${inputClass} mt-1 text-xs`}>
                <option value="">None (management draft only)</option>
                {resolutions.filter((r) => r.state !== "INVALIDATED").map((r) => <option key={r.id} value={r.id}>{r.facts.entity_name || "Unnamed"} · rev {r.revision} · {words(r.state)}</option>)}
              </select>
            </label>
            <label className="block text-[11px] font-semibold text-muted">Prior-period trial balance (comparatives)
              <select value={priorId} onChange={(e) => setPriorId(e.target.value)} className={`${inputClass} mt-1 text-xs`}>
                <option value="">None</option>
                {approved.filter((t) => t.id !== tbId).map((t) => <option key={t.id} value={t.id}>{t.filename} · v{t.version}</option>)}
              </select>
            </label>
            <label className="flex items-center gap-1 text-[11px] text-ink"><input type="checkbox" checked={schedules.first_period === "true"} onChange={(e) => set("first_period", e.target.checked ? "true" : "")} />First period of reporting (no comparatives exist)</label>
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="block text-[11px] font-semibold text-muted">Opening share capital<input inputMode="decimal" value={schedules.share_capital_opening ?? ""} onChange={(e) => set("share_capital_opening", e.target.value)} className={`${inputClass} mt-1 text-xs`} /></label>
              <label className="block text-[11px] font-semibold text-muted">Borrowings due after one year<input inputMode="decimal" value={schedules.borrowings_due_after_one_year ?? ""} onChange={(e) => set("borrowings_due_after_one_year", e.target.value)} className={`${inputClass} mt-1 text-xs`} /></label>
            </div>
            <label className="block text-[11px] font-semibold text-muted">Dividend declaration evidence<input value={schedules.dividends_evidence ?? ""} onChange={(e) => set("dividends_evidence", e.target.value)} placeholder="Board minute reference" className={`${inputClass} mt-1 text-xs`} /></label>
            <details className="rounded-lg border border-line p-2 text-[11px]">
              <summary className="cursor-pointer font-semibold text-muted">Cash movements (for a cash flow statement)</summary>
              <div className="mt-2 grid gap-2">
                {Object.entries(Object.keys(cashFields).length ? cashFields : CASH_DEFAULT).map(([k, label]) => (
                  <label key={k} className="block text-muted">{label}<input inputMode="decimal" value={schedules[k] ?? ""} onChange={(e) => set(k, e.target.value)} className={`${inputClass} mt-1 text-xs`} /></label>
                ))}
              </div>
            </details>
            {error && <p role="alert" className="text-[11px] text-bad">{error}</p>}
            <Btn type="submit" variant="primary" busy={busy} disabled={!tbId}>Assemble</Btn>
          </form>
        </Panel>
        <Panel title="Report packages" subtitle="A change after a sign-off makes a new version">
          {packages.length === 0 ? <p className="text-xs text-muted">None yet.</p> : (
            <ul className="space-y-1.5 text-[11px]">
              {packages.map((p) => (
                <li key={p.id}><button type="button" onClick={() => show(() => getPackage(p.id))}
                  className={`w-full rounded-lg border p-2 text-left ${pkg?.id === p.id ? "border-accent bg-accent/5" : "border-line"}`}>
                  <Badge tone={p.state === "APPROVED" ? "ok" : p.state === "SUPERSEDED" ? "neutral" : "warn"}>{words(p.state)}</Badge> <b>{p.entity || "Unnamed entity"}</b>
                  <span className="text-muted"> v{p.version} · P0 {p.counts.P0 ?? 0} · P1 {p.counts.P1 ?? 0}</span>
                </button></li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      {pkg && result ? (
        <div className="space-y-4">
          <Panel title={`${result.profile.entity || "Report package"} · version ${pkg.version}`} subtitle={`${words(pkg.state)} · ${result.watermark}`}>
            <div className="space-y-3">
              {pkg.stale_reasons.length > 0 && <Callout tone="bad" title="Out of date — rebuild">{pkg.stale_reasons.map((r) => <span key={r} className="block">{r}</span>)}</Callout>}
              <KeyGrid items={[
                ["Framework", result.profile.framework ? `${words(result.profile.framework)} · ${result.profile.edition ?? ""}` : "None (management)"],
                ["Layout", words(result.profile.family)], ["Period", `${result.profile.period_start || "?"} to ${result.profile.period_end || "?"}`],
                ["Resolution", result.profile.resolution_id ? `rev ${result.profile.resolution_revision} · ${words(result.profile.resolution_state ?? "")}` : "None"],
              ]} />
              {/* 03 Readiness banner */}
              <Callout tone={result.counts.P0 ? "bad" : result.counts.P1 ? "warn" : "info"}
                title={`P0 ${result.counts.P0} · P1 ${result.counts.P1} · P2 ${result.counts.P2} — ${result.halted ? `halted: ${words(result.halted)}` : words(result.state)}`}>
                Statutory release is blocked while any P0 or P1 is open; a watermarked draft is still available.
              </Callout>
              {/* 04 Top-line results */}
              {Object.keys(result.headline).length > 0 && (
                <KeyGrid items={[["Revenue", money(result.headline.revenue)], ["Profit before tax", money(result.headline.profit_before_tax)],
                  ["Net assets", money(result.headline.net_assets)], ["Cash", money(result.headline.cash)]]} />
              )}
            </div>
          </Panel>

          {result.statements.length > 0 && (
            <Panel title="Statements" subtitle="Every statement is drawn from the same approved facts">
              {/* 05 Required statement matrix */}
              <table className="w-full text-left text-[11px]">
                <thead className="text-muted"><tr><th scope="col" className="py-1">Statement</th><th scope="col">Requirement</th><th scope="col">Status</th></tr></thead>
                <tbody>
                  {result.statements.map((s) => (
                    <tr key={s.statement_id} className={`cursor-pointer border-t border-line ${statement?.statement_id === s.statement_id ? "bg-accent/5" : ""}`} onClick={() => setStatementId(s.statement_id)}>
                      <td className="py-1 font-semibold"><button type="button" className="text-left" onClick={() => setStatementId(s.statement_id)}>{s.title}</button></td>
                      <td>{words(s.requiredness)}</td><td><Badge tone={STATUS_TONE[s.status] ?? "neutral"}>{words(s.status)}</Badge></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {statement && <div className="mt-3"><Heading>{statement.title}</Heading><StatementPreview statement={statement} /></div>}
            </Panel>
          )}

          {result.assertions.length > 0 && (
            <Panel title="Cross-statement checks" subtitle="Recomputed at full precision; nothing is plugged">
              {/* 06 Assertion ledger */}
              <ul className="space-y-1 text-[11px]">
                {result.assertions.map((a) => (
                  <li key={a.assertion_id} className="rounded-lg border border-line p-2">
                    <button type="button" className="flex w-full flex-wrap items-center gap-1.5 text-left" onClick={() => setAssertionId(assertionId === a.assertion_id ? null : a.assertion_id)}>
                      <Badge tone={STATUS_TONE[a.status] ?? "neutral"}>{words(a.status)}</Badge><b>{a.assertion_id}</b>{a.title}
                      {a.status === "FAIL" && <span className="text-bad">difference {money(a.residual)}</span>}
                    </button>
                    {assertionId === a.assertion_id && (
                      <div className="mt-1 space-y-0.5 text-muted">
                        <p>{a.formula}</p>
                        <p>{Object.entries(a.operands).map(([k, v]) => `${words(k)} ${money(v)}`).join(" · ")}</p>
                        {a.detail && <p>{a.detail}</p>}
                        {a.candidates.length > 0 && <p>Look at: {a.candidates.join("; ")}</p>}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </Panel>
          )}

          {result.notes.length > 0 && (
            <Panel title="Notes and evidence" subtitle="Each note is bound to evidence; a disclosure owner (not the author) approves">
              {/* 07 Notes and evidence panel */}
              <Checklist>
                {result.notes.map((n) => (
                  <NoteRow key={`${pkg.id}-${n.requirement_id}`} note={n} busy={busy}
                    onSubmit={(body) => open && show(() => submitDisclosure(pkg.id, { requirement_id: n.requirement_id, ...body }))}
                    onApprove={() => open && show(() => approveDisclosure(pkg.id, n.requirement_id))} />
                ))}
              </Checklist>
            </Panel>
          )}

          <Panel title="Findings" subtitle="Owner and exact action for each; only P2 review items can be disposed">
            <ul className="space-y-1.5 text-[11px]">
              {result.findings.map((f) => (
                <li key={f.code} className="rounded-lg border border-line p-2 text-ink">
                  <div className="flex flex-wrap items-center gap-1.5"><Badge tone={SEVERITY_TONE[f.severity]}>{f.severity}</Badge><b>{words(f.code)}</b>
                    <span className="text-muted">{f.rule} · owner: {f.owner}{f.release_only ? " · release gate" : ""}</span></div>
                  <p className="mt-1">{f.message}</p><p className="text-muted">Action: {f.action}</p>
                  {f.disposition ? <p className="text-muted">Disposed by {f.disposition.by}: {f.disposition.reason}</p> : f.severity === "P2" && open && (
                    <div className="mt-1 flex gap-1.5">
                      <input aria-label={`Disposition for ${f.code}`} value={disposal[f.code] ?? ""} onChange={(e) => setDisposal({ ...disposal, [f.code]: e.target.value })} placeholder="Reviewer's reason" className={`${inputClass} min-w-0 flex-1 text-xs`} />
                      <Btn busy={busy} disabled={!(disposal[f.code] ?? "").trim()} onClick={() => show(() => disposeFinding(pkg.id, f.code, disposal[f.code]))}>Dispose</Btn>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </Panel>

          {/* 08 Approval and export controls */}
          <Panel title="Sign-off and export" subtitle="Four separate sign-offs; exports are watermarked unless every statutory gate passes">
            <div className="space-y-3">
              <Checklist>
                {ROLES.map(([role, label]) => {
                  const s = pkg.signoffs[role];
                  return <CheckRow key={role} state={s ? "pass" : "todo"} title={label} detail={s ? `Signed by ${s.by}` : undefined}
                    right={!s && open ? <Btn busy={busy} disabled={!result.ready_for_signoff} title={result.ready_for_signoff ? undefined : "Open findings or notes remain"}
                      onClick={() => show(() => signPackage(pkg.id, role))}>Sign</Btn> : null} />;
                })}
              </Checklist>
              <div className="flex flex-wrap gap-2">
                <Btn variant="quiet" busy={busy} onClick={() => run(async () => setRelease(await packageReleaseCheck(pkg.id)))}>Release check</Btn>
                <Btn variant="secondary" busy={busy} disabled={!open} onClick={() => run(() => downloadPackage(pkg.id, "json"))}>Export JSON</Btn>
                <Btn variant="secondary" busy={busy} disabled={!open} onClick={() => run(() => downloadPackage(pkg.id, "csv"))}>Export CSV</Btn>
              </div>
              {release && (
                <Callout tone={release.statutory_release_allowed ? "ok" : "warn"} title={release.statutory_release_allowed ? "Statutory release allowed" : "Statutory release blocked"}>
                  {release.reasons.slice(0, 8).map((r) => <span key={r} className="block">{r}</span>)}
                </Callout>
              )}
              <Heading>History</Heading>
              <ol className="space-y-1 text-[11px] text-ink">
                {pkg.history.map((h, i) => <li key={i} className="flex flex-wrap gap-2"><DateCell iso={h.at} /><span className="font-semibold">{words(h.action)}</span><span className="text-muted">by {h.actor_id} · v{h.version}</span></li>)}
              </ol>
              <ControlNote>Rule set {result.profile.ruleset.id} · {words(result.profile.ruleset.status)} · {shortId("fp", pkg.fingerprint.replace("sha256:", ""))}. Word/PDF publication and filing are Documents 06 and 07.</ControlNote>
            </div>
          </Panel>
        </div>
      ) : <Panel title="Package" subtitle="Assemble or open a package"><p className="text-xs text-muted">Nothing selected.</p></Panel>}
    </div>
  );
}

const CASH_DEFAULT: Record<string, string> = {
  depreciation_amortisation: "Depreciation and amortisation", fixed_asset_additions: "Cash paid for fixed assets",
  disposal_proceeds: "Disposal proceeds", disposals_nbv: "Carrying amount disposed", current_tax_charge: "Current tax charge",
  tax_paid: "Tax paid", interest_paid: "Interest paid", interest_received: "Interest received", borrowings_drawn: "Borrowings drawn",
  borrowings_repaid: "Borrowings repaid", shares_issued: "Shares issued for cash", dividends_paid: "Dividends paid",
  fx_effect: "Effect of exchange rates",
};
