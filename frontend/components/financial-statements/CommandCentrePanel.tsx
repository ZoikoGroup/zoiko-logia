"use client";

import { useEffect, useState } from "react";
import { Badge, Btn, Callout, ControlNote, KeyGrid, Panel, inputClass, shortId, type Tone } from "@/components/workflow-ui/kit";
import {
  getAcceptanceRegister, getCommandCentre, listPackages, runGolden, type AcceptanceCase, type CommandCentre, type GoldenRun,
  type PackageSummary,
} from "@/lib/financial-statements-api";

// Integration QA command centre — Document 08 (ZL-FSR-ENG-008) §10. Diagnostic only: no override actions.

const TONE: Record<string, Tone> = { PASS: "ok", FAIL: "bad", BLOCKED: "bad", NOT_STARTED: "neutral", NOT_AVAILABLE: "neutral",
  NOT_EVALUATED: "warn", EXEMPT: "info", NOT_APPLICABLE: "neutral" };
const COVERAGE_TONE: Record<string, Tone> = { AUTOMATED: "ok", PARTIAL: "warn", NOT_IMPLEMENTED: "bad", NOT_APPLICABLE: "neutral",
  BLOCKED_AS_UNSUPPORTED: "info" };
const words = (s: string) => s.replace(/_/g, " ").toLowerCase();

export function CommandCentrePanel() {
  const [list, setList] = useState<PackageSummary[]>([]);
  const [packageId, setPackageId] = useState("");
  const [view, setView] = useState<CommandCentre | null>(null);
  const [cases, setCases] = useState<AcceptanceCase[]>([]);
  const [coverage, setCoverage] = useState("ALL");
  const [golden, setGolden] = useState<GoldenRun | null>(null);
  const [showManifest, setShowManifest] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    listPackages().then(setList).catch(() => setList([]));
    getAcceptanceRegister().then((r) => setCases(r.cases)).catch(() => setCases([]));
  }, []);

  async function run(call: () => Promise<void>) {
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
  function choose(id: string) {
    setPackageId(id);
    setView(null);
    if (id) void run(async () => setView(await getCommandCentre(id)));
  }

  const counts = cases.reduce<Record<string, number>>((acc, c) => ({ ...acc, [c.coverage]: (acc[c.coverage] ?? 0) + 1 }), {});
  const shown = cases.filter((c) => coverage === "ALL" || c.coverage === coverage);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="block min-w-64 text-[11px] font-semibold text-muted">Report package
          <select value={packageId} onChange={(e) => choose(e.target.value)} className={`${inputClass} mt-1 text-xs`}>
            <option value="">Choose…</option>
            {list.filter((p) => p.state !== "SUPERSEDED").map((p) => <option key={p.id} value={p.id}>{p.entity || "Unnamed entity"} · v{p.version}</option>)}
          </select>
        </label>
        <Btn busy={busy} onClick={() => run(async () => setGolden(await runGolden()))}>Run golden dataset</Btn>
      </div>
      {error && <p role="alert" className="text-[11px] text-bad">{error}</p>}

      {view && (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="min-w-0 space-y-4">
            {/* Context strip */}
            <Panel title={view.context.entity || "Entity"} subtitle={`${view.context.period_start} – ${view.context.period_end} · ${view.context.currency}`}>
              <KeyGrid items={[["Framework", view.context.framework_edition ?? "unresolved"], ["Release state", words(view.context.release_state)],
                ["Package", shortId("pkg", view.context.package_hash.replace("sha256:", ""))], ["Decision", view.context.applicability_decision_id ?? "none"]]} />
            </Panel>
            {/* Service chain G0–G7 */}
            <Panel title="Service chain" subtitle="Each gate's owner, last result and canonical error">
              <ol className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-4">
                {view.chain.map((g) => (
                  <li key={g.gate} className="rounded-lg border border-line p-2 text-[11px]">
                    <div className="flex items-center gap-1.5"><Badge tone={TONE[g.status] ?? "neutral"}>{words(g.status)}</Badge><b>{g.gate} {g.title}</b></div>
                    <p className="mt-1 text-ink">{g.detail}</p>
                    <p className="text-muted">{g.owner}{g.error_code ? ` · ${g.error_code}` : ""}{g.retriable ? " · retriable" : ""}</p>
                  </li>
                ))}
              </ol>
            </Panel>
            {/* Invariant table */}
            <Panel title="Invariants INV-01 – INV-16" subtitle="Deterministic controls at full precision">
              <table className="w-full text-left text-[11px]">
                <thead className="text-muted"><tr><th scope="col" className="py-1">Invariant</th><th scope="col">Status</th><th scope="col">Detail</th></tr></thead>
                <tbody>{view.invariants.map((i) => (
                  <tr key={i.id} className="border-t border-line"><td className="py-1"><b>{i.id}</b> {i.title}</td>
                    <td><Badge tone={TONE[i.status] ?? "neutral"}>{words(i.status)}</Badge></td>
                    <td className="text-muted">{i.detail}{i.residual && i.residual !== "0" ? ` · residual ${i.residual}` : ""}</td></tr>
                ))}</tbody>
              </table>
            </Panel>
            {/* Export simulation */}
            <Panel title="Export simulation" subtitle={view.publication_disabled_reason ?? "Gates G0–G5 pass"}>
              {view.export_simulation.length === 0 ? <p className="text-xs text-muted">No rendered channels yet (Publish tab).</p> : (
                <ul className="space-y-1 text-[11px]">{view.export_simulation.map((e) => (
                  <li key={e.id}><Badge tone={e.parity ? "ok" : "bad"}>{e.parity ? "parity" : "diverges"}</Badge> {e.channel.toUpperCase()} · {words(e.audience)} {e.issues.join(" ")}</li>
                ))}</ul>
              )}
            </Panel>
          </div>
          <aside className="space-y-4">
            {/* Release-gates rail */}
            <Panel title="Release gates" subtitle="Hard blockers are never masked by exceptions">
              <p className="text-[11px] font-bold text-bad">Hard ({view.rail.hard.length})</p>
              <ul className="space-y-1 text-[11px]">{view.rail.hard.map((r) => <li key={`${r.source}-${r.code}`}>{r.source}: {words(r.code)} — {r.message}</li>)}</ul>
              <p className="mt-2 text-[11px] font-bold text-accent-ink">Soft ({view.rail.soft.length})</p>
              <ul className="space-y-1 text-[11px]">{view.rail.soft.slice(0, 12).map((r, i) => <li key={`${r.code}-${i}`}>{r.source}: {r.message}</li>)}</ul>
            </Panel>
            {/* Evidence drawer */}
            <Panel title="Reporting package manifest" subtitle={`Status ${words(view.manifest.status)}`}>
              <ul className="space-y-0.5 text-[11px]">
                {view.manifest.sources.map((s) => <li key={s.source_id}>{s.provenance} v{s.ingestion_version} · {s.sha256.slice(0, 12)}…</li>)}
              </ul>
              <p className="mt-1 text-[11px] text-muted">Idempotency {shortId("frp", view.manifest.idempotency_key.replace("sha256:", ""))} · audit root {shortId("aud", view.manifest.audit_event_root.replace("sha256:", ""))}</p>
              <Btn variant="quiet" onClick={() => setShowManifest(!showManifest)}>{showManifest ? "Hide" : "Show"} full manifest</Btn>
              {showManifest && <pre className="mt-2 max-h-80 overflow-auto rounded bg-soft p-2 text-[10px]">{JSON.stringify(view.manifest, null, 2)}</pre>}
            </Panel>
            <Panel title="Support levels" subtitle="A jurisdiction in a list is not certified support">
              <ul className="space-y-1 text-[11px]">{view.support.map((s) => <li key={s.scope}><Badge tone={s.level === "UNSUPPORTED" ? "bad" : s.level === "EXPERIMENTAL" ? "warn" : "info"}>{words(s.level)}</Badge> {s.scope}<span className="block text-muted">{s.why}</span></li>)}</ul>
            </Panel>
          </aside>
        </div>
      )}

      {golden && (
        <Panel title="Golden dataset" subtitle={golden.label ?? golden.fixture}>
          {golden.aborted ? <Callout tone="bad" title="Aborted">{golden.reason}</Callout> : (
            <div className="space-y-2 text-[11px]">
              <p className="text-muted">{golden.oracle_status}</p>
              {Object.entries(golden.runs ?? {}).map(([variant, r]) => (
                <p key={variant}><Badge tone={(golden.mismatches?.[variant] ?? []).length ? "bad" : "ok"}>{(golden.mismatches?.[variant] ?? []).length ? "mismatch" : "oracle met"}</Badge> <b>{words(variant)}</b> · operating profit {r.figures.operating_profit} · PBT {r.figures.profit_before_tax} · profit {r.figures.profit}</p>
              ))}
              {golden.dispute && <Callout tone="warn" title={`Classification dispute: £${golden.dispute.difference}`}>
                {Object.entries(golden.dispute.operating_profit).map(([k, v]) => `${words(k)} ${v}`).join(" vs ")} · accounts: {golden.dispute.accounts.join(", ")}. {golden.dispute.disposition}
              </Callout>}
            </div>
          )}
        </Panel>
      )}

      <Panel title="Acceptance register — 60 cases" subtitle="Each case points at executable tests; CI, not this list, reports a pass">
        <div className="mb-2 flex flex-wrap gap-1" role="group" aria-label="Coverage filter">
          {["ALL", "AUTOMATED", "PARTIAL", "BLOCKED_AS_UNSUPPORTED", "NOT_IMPLEMENTED", "NOT_APPLICABLE"].map((c) => (
            <button key={c} type="button" aria-pressed={coverage === c} onClick={() => setCoverage(c)}
              className={`rounded-md border px-2 py-1 text-[10px] font-bold ${coverage === c ? "border-accent bg-accent/10" : "border-line text-muted"}`}>
              {c === "ALL" ? `All ${cases.length}` : `${words(c)} ${counts[c] ?? 0}`}
            </button>
          ))}
        </div>
        <table className="w-full text-left text-[11px]">
          <thead className="text-muted"><tr><th scope="col" className="py-1">Case</th><th scope="col">Coverage</th><th scope="col">Tests / note</th></tr></thead>
          <tbody>{shown.map((c) => (
            <tr key={c.id} className="border-t border-line align-top">
              <td className="py-1"><b>{c.id}</b> {c.stimulus}</td>
              <td><Badge tone={COVERAGE_TONE[c.coverage] ?? "neutral"}>{words(c.coverage)}</Badge></td>
              <td className="text-muted">{c.tests.map((t) => <span key={t} className="block font-mono text-[10px]">{t.split("::")[1]}</span>)}{c.note}</td>
            </tr>
          ))}</tbody>
        </table>
      </Panel>
      <ControlNote>Internal QA is never an independent audit. Production status stays NO-GO for statutory claims until reviewed rule packs, signed golden oracles and certified adapters exist.</ControlNote>
    </div>
  );
}
