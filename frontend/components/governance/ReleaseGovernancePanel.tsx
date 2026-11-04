"use client";

// WF-01 platform release governance, shown on Release Gates (no new sidebar
// destination). Every status here is the server's: the verdict, gate states,
// QA ledger counts and fixture provisioning are read, never derived, and an
// unknown value is shown as NOT RUN, never as passing. Actions are offered by
// role; the server enforces the role, the governance tenant and independence.

import { useState } from "react";
import { FileCheck2, FlaskConical, Gavel, Landmark, ShieldAlert } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useLiveData } from "@/components/overview/useLiveData";
import { Badge, Button, DetailRows, EmptyState, ErrorNote, Panel, inputClass, useMutation } from "@/components/operations/ui";
import {
  adjudicateQaObservation, adoptGapOwnership, createQaRun, executeQaRun, getGovernanceOverview, getQaObservations,
  importAuthorityRegister, importQaPack, provisionQaFixtures, ratifyGapOwnership, recordAsBuilt, recordReleaseVerdict,
  verifyAsBuilt, type VerdictGateState, type GovernanceOverview, type QaRunView,
} from "@/lib/api";

const GATE_LABEL: Record<string, string> = {
  authority: "Document authority", ownership: "Gap ownership", qa_pack: "QA pack & fixtures",
  asbuilt: "As-built manifest", runtime_qa: "Runtime QA (292 observations)", signing: "Record signing",
};
const GATE_TONE: Record<VerdictGateState, "ok" | "warn" | "bad" | "neutral"> = {
  SATISFIED: "ok", PENDING: "warn", BLOCKED: "bad", NOT_RUN: "neutral",
};
const PINNED_FIELDS = ["release_sha", "environment", "model", "retriever", "prompt_version", "policy_version", "region",
  "oracle_version", "adapter_id"] as const;

export function stateTone(state: string): "ok" | "warn" | "bad" | "neutral" | "info" {
  if (["SATISFIED", "PASSED", "VERIFIED", "RATIFIED", "CONNECTED", "PROVISIONED", "MAPPED", "GO"].includes(state)) return "ok";
  if (["BLOCKED", "FAILED", "REJECTED", "NO_GO", "UNMAPPED", "FAILED_TO_EXECUTE", "MISSING", "UNSUPPORTED"].includes(state)) return "bad";
  if (["PENDING", "INCONCLUSIVE", "UNVERIFIED", "ADOPTED_PENDING_RATIFICATION", "EXECUTED"].includes(state)) return "warn";
  return "neutral";
}

/** "NOT_RUN" -> "NOT RUN": shown, never hidden or blanked. */
export function label(state: string | null | undefined): string {
  return (state || "NOT_RUN").replaceAll("_", " ");
}

export function ReleaseGovernancePanel() {
  const { profile } = useAuth();
  const role = profile?.role ?? "";
  const { data, error, loading, reload } = useLiveData("release-governance", (token, signal) => getGovernanceOverview(token, signal), 45_000);

  if (loading && !data) return <Panel title="Platform release governance (WF-01)"><p className="text-sm text-muted">Loading the release verdict…</p></Panel>;
  if (error && !data) {
    return (
      <Panel title="Platform release governance (WF-01)">
        <EmptyState icon={ShieldAlert} title="Not available to this account">{error}</EmptyState>
      </Panel>
    );
  }
  if (!data) return null;
  return (
    <div className="space-y-4" aria-label="Platform release governance">
      <Verdict data={data} role={role} onChanged={reload} />
      <div className="grid gap-4 xl:grid-cols-2">
        <Authority data={data} role={role} selfId={profile?.id} onChanged={reload} />
        <AsBuilt data={data} role={role} selfId={profile?.id} onChanged={reload} />
      </div>
      <RuntimeQa data={data} role={role} onChanged={reload} />
      {role === "Independent QA" && <Adjudication runs={data.runs} selfId={profile?.id} onChanged={reload} />}
    </div>
  );
}

function Verdict({ data, role, onChanged }: { data: GovernanceOverview; role: string; onChanged: () => void }) {
  const m = useMutation();
  const v = data.verdict;
  return (
    <Panel title="Platform release verdict" meta={`Evidence ${v.evidence_sha256.slice(0, 12)}…`}
      action={role === "CTO" ? <Button busy={m.busy === "verdict"} onClick={() => m.run("verdict", (t) => recordReleaseVerdict(t)).then((ok) => ok && onChanged())}>Record verdict</Button> : undefined}>
      <div className={`mb-3 flex items-center gap-3 rounded-lg border p-3 ${v.verdict === "GO" ? "border-ok/40 bg-ok/5" : "border-bad/40 bg-bad/5"}`}>
        <Gavel size={20} className={v.verdict === "GO" ? "text-ok" : "text-bad"} />
        <p className="text-sm text-ink"><b data-testid="verdict">{v.verdict === "GO" ? "GO" : "NO-GO"}</b> — computed by the server now; GO only when every gate is satisfied by recorded evidence.</p>
      </div>
      <ul className="space-y-2">
        {Object.entries(v.gates).map(([key, gate]) => (
          <li key={key} className="grid grid-cols-[minmax(0,12rem)_auto_minmax(0,1fr)] items-start gap-2 text-sm">
            <span className="font-semibold text-ink">{GATE_LABEL[key] ?? key}</span>
            <Badge tone={GATE_TONE[gate.state] ?? "neutral"}>{label(gate.state)}</Badge>
            <span className="text-muted">{gate.reason}</span>
          </li>
        ))}
      </ul>
      <ErrorNote message={m.error} />
    </Panel>
  );
}

function Authority({ data, role, selfId, onChanged }: { data: GovernanceOverview; role: string; selfId?: string; onChanged: () => void }) {
  const m = useMutation();
  const s = data.authority.summary;
  const own = data.ownership.current;
  const act = (key: string, fn: (t: string) => Promise<unknown>) => m.run(key, fn).then((ok) => ok && onChanged());
  return (
    <Panel title="Document authority & gap ownership" meta="A1 · D1">
      <DetailRows rows={[
        ["Documents", s.documents],
        ["Unresolved IDs", s.unresolved_collisions.length ? s.unresolved_collisions.join(", ") : "None"],
        ["Not in repository", s.states.EVIDENCE_UNAVAILABLE_IN_REPO ?? 0],
        ["Ratified IDs", s.states.CANONICAL_RATIFIED ?? 0],
        ["Gap ownership", <Badge key="o" tone={stateTone(own.status)}>{label(own.status)}</Badge>],
      ]} />
      <div className="mt-3 flex flex-wrap gap-2">
        {role === "Document Control" && <>
          <Button busy={m.busy === "import"} onClick={() => act("import", importAuthorityRegister)}>Import register</Button>
          <Button busy={m.busy === "adopt"} onClick={() => act("adopt", adoptGapOwnership)}>Adopt gap allocation</Button>
        </>}
        {role === "Chief Architect" && own.status === "ADOPTED_PENDING_RATIFICATION" && own.decision_id && own.content_sha256 && (
          <Button variant="primary" busy={m.busy === "ratify"} title={selfId ? "Must be someone other than the adopter" : undefined}
            onClick={() => act("ratify", (t) => ratifyGapOwnership(t, own.decision_id!, own.content_sha256!))}>Ratify gap allocation</Button>
        )}
      </div>
      <ErrorNote message={m.error} />
    </Panel>
  );
}

function AsBuilt({ data, role, onChanged }: { data: GovernanceOverview; role: string; selfId?: string; onChanged: () => void }) {
  const m = useMutation();
  const [note, setNote] = useState("");
  const manifest = data.asbuilt.manifest;
  const unmapped = manifest?.mappings.filter((x) => x.status !== "MAPPED").length ?? 0;
  const act = (key: string, fn: (t: string) => Promise<unknown>) => m.run(key, fn).then((ok) => ok && onChanged());
  return (
    <Panel title="As-built manifest" meta="A2"
      action={role === "QA Automation" ? <Button busy={m.busy === "record"} onClick={() => act("record", recordAsBuilt)}>Record manifest</Button> : undefined}>
      {manifest ? (
        <DetailRows rows={[
          ["Commit", manifest.commit_sha ? manifest.commit_sha.slice(0, 12) : "—"],
          ["Tree", manifest.tree_clean ? "Clean" : "Uncommitted changes"],
          ["Environment", manifest.environment],
          ["Requirements", `${manifest.mappings.length - unmapped} mapped · ${unmapped} unmapped`],
          ["Verification", <Badge key="v" tone={stateTone(manifest.verification)}>{label(manifest.verification)}</Badge>],
        ]} />
      ) : <EmptyState icon={FileCheck2} title="No manifest recorded">Verification is NOT RUN until one is recorded and checked by someone else.</EmptyState>}
      {role === "CTO" && manifest && (
        <div className="mt-3 flex flex-wrap gap-2">
          <input className={inputClass} aria-label="Verification note" placeholder="Note" value={note} onChange={(e) => setNote(e.target.value)} />
          <Button variant="primary" busy={m.busy === "verify"} onClick={() => act("verify", (t) => verifyAsBuilt(t, manifest.id, "VERIFIED", note))}>Verify</Button>
          <Button variant="danger" busy={m.busy === "reject"} onClick={() => act("reject", (t) => verifyAsBuilt(t, manifest.id, "REJECTED", note))}>Reject</Button>
        </div>
      )}
      <ErrorNote message={m.error} />
    </Panel>
  );
}

function RuntimeQa({ data, role, onChanged }: { data: GovernanceOverview; role: string; onChanged: () => void }) {
  const m = useMutation();
  const [pinned, setPinned] = useState<Record<string, string>>({});
  const [runId, setRunId] = useState("");
  const [cases, setCases] = useState("");
  const qa = data.qa;
  const status = qa.observation_status ?? {};
  const act = (key: string, fn: (t: string) => Promise<unknown>) => m.run(key, fn).then((ok) => ok && onChanged());
  const byFixture = Object.entries(data.fixtures.fixtures).map(([id, f]) => {
    // Files no case uses (provision NOT_REQUIRED) are not counted as missing.
    const files = data.fixtures.files.filter((x) => x.fixture_id === id && x.provision !== "NOT_REQUIRED");
    return { id, ...f, files, provisioned: files.filter((x) => x.provision === "PROVISIONED").length,
      unsupported: files.filter((x) => x.provision === "UNSUPPORTED" || !x.uploadable).length };
  });
  return (
    <Panel title="Runtime QA ledger" meta="A3 · Document 01, 72 cases"
      action={<Badge tone={stateTone(data.adapter.readiness)}>Adapter {label(data.adapter.readiness)}</Badge>}>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {[["Planned observations", qa.planned_observations], ["Not run", status.NOT_RUN ?? qa.planned_observations],
          ["Blocked", status.BLOCKED ?? 0], ["Qualifying runs", qa.qualifying_runs ?? 0],
          ["P0 cases passed", `${qa.p0_passed ?? 0} / ${qa.p0_total ?? 38}`]].map(([k, v]) => (
          <div key={k as string} className="rounded-lg border border-line p-3">
            <div className="text-xl font-extrabold text-ink">{v}</div><div className="text-xs text-muted">{k}</div>
          </div>
        ))}
      </div>
      {data.adapter.reason && <p className="mt-2 text-xs text-muted">Adapter: {data.adapter.reason}</p>}
      <h3 className="mt-4 text-sm font-bold text-ink">Fixtures F0–F8</h3>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-xs text-muted"><tr><th className="py-1 pr-3">Fixture</th><th className="pr-3">Manifest</th><th className="pr-3">Signature</th><th className="pr-3">Files provisioned</th><th>Specification</th></tr></thead>
          <tbody>
            {byFixture.map((f) => (
              <tr key={f.id} className="border-t border-line align-top">
                <td className="py-1.5 pr-3 font-semibold text-ink">{f.id}</td>
                <td className="pr-3"><Badge tone={stateTone(f.status)}>{label(f.status)}</Badge></td>
                <td className="pr-3"><Badge tone="neutral">{label(f.signature)}</Badge></td>
                <td className="pr-3 text-ink">{f.provisioned} / {f.files.length}{f.unsupported ? ` · ${f.unsupported} not uploadable` : ""}</td>
                <td className="text-muted">{f.specification}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {role === "QA Automation" && (
        <div className="mt-4 space-y-3 border-t border-line pt-3">
          <div className="flex flex-wrap gap-2">
            <Button busy={m.busy === "pack"} onClick={() => act("pack", importQaPack)}>Import QA pack</Button>
            <Button busy={m.busy === "provision"} onClick={() => act("provision", provisionQaFixtures)}>Provision fixtures</Button>
          </div>
          <fieldset className="grid gap-2 sm:grid-cols-3">
            <legend className="mb-1 text-xs font-bold uppercase tracking-wider text-muted">Pinned run configuration (every field required)</legend>
            {PINNED_FIELDS.map((f) => (
              <input key={f} className={inputClass} aria-label={f} placeholder={f} value={pinned[f] ?? ""}
                onChange={(e) => setPinned({ ...pinned, [f]: e.target.value })} />
            ))}
          </fieldset>
          <Button variant="primary" busy={m.busy === "run"} onClick={() => act("run", (t) => createQaRun(t, pinned))}>Start pinned run</Button>
          <div className="flex flex-wrap gap-2">
            <select className={inputClass} aria-label="Run" value={runId} onChange={(e) => setRunId(e.target.value)}>
              <option value="">Select a run</option>
              {data.runs.map((r) => <option key={r.id} value={r.id}>{runLabel(r)}</option>)}
            </select>
            <input className={inputClass} aria-label="Case IDs" placeholder="Case IDs, e.g. E05, J03 (blank = all)" value={cases} onChange={(e) => setCases(e.target.value)} />
            <Button disabled={!runId} busy={m.busy === "execute"} onClick={() => act("execute", (t) => executeQaRun(t, runId,
              cases.split(/[\s,]+/).filter(Boolean), 10))}>Execute next 10</Button>
          </div>
        </div>
      )}
      <ErrorNote message={m.error} />
    </Panel>
  );
}

function runLabel(r: QaRunView): string {
  return `${r.created_at.slice(0, 16).replace("T", " ")} · ${r.environment} · ${r.qualifying ? "qualifying" : "not qualifying"}`;
}

function Adjudication({ runs, onChanged }: { runs: QaRunView[]; selfId?: string; onChanged: () => void }) {
  const [runId, setRunId] = useState(runs[0]?.id ?? "");
  const observations = useLiveData(`qa-observations:${runId}`, (token, signal) =>
    runId ? getQaObservations(token, runId, signal) : Promise.resolve([]), 30_000);
  const m = useMutation();
  const [oracle, setOracle] = useState("");
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const pending = (observations.data ?? []).filter((o) => o.state === "EXECUTED" && o.adjudication === "NOT_ADJUDICATED");
  const decide = (id: string, verdict: "PASSED" | "FAILED" | "INCONCLUSIVE") =>
    m.run(id + verdict, (t) => adjudicateQaObservation(t, id, verdict, oracle, reasons[id] ?? ""))
      .then((ok) => { if (ok) { observations.reload(); onChanged(); } });
  return (
    <Panel title="Adjudication queue" meta="Independent QA · not the run's starter">
      <div className="mb-3 flex flex-wrap gap-2">
        <select className={inputClass} aria-label="Run to adjudicate" value={runId} onChange={(e) => setRunId(e.target.value)}>
          {runs.map((r) => <option key={r.id} value={r.id}>{runLabel(r)}</option>)}
        </select>
        <input className={inputClass} aria-label="Oracle version" placeholder="Oracle version (required)" value={oracle} onChange={(e) => setOracle(e.target.value)} />
      </div>
      {pending.length === 0 ? <EmptyState icon={FlaskConical} title="Nothing awaiting adjudication">Blocked and failed observations cannot be adjudicated.</EmptyState> : (
        <ul className="space-y-3">
          {pending.map((o) => (
            <li key={o.id} className="rounded-lg border border-line p-3 text-sm">
              <p className="font-semibold text-ink">{o.case_id} · repetition {o.repetition}
                {o.automated_checks?.mock_completion === true && <span className="ml-2"><Badge tone="bad">Mock completion, not a model answer</Badge></span>}</p>
              <p className="mt-1 whitespace-pre-wrap text-muted">{o.output_excerpt || "(empty response)"}</p>
              <input className={`${inputClass} mt-2`} aria-label={`Reason for ${o.case_id} repetition ${o.repetition}`} placeholder="Reason (required)"
                value={reasons[o.id] ?? ""} onChange={(e) => setReasons({ ...reasons, [o.id]: e.target.value })} />
              <div className="mt-2 flex flex-wrap gap-2">
                {(["PASSED", "FAILED", "INCONCLUSIVE"] as const).map((v) => (
                  <Button key={v} variant={v === "FAILED" ? "danger" : "secondary"} disabled={!oracle.trim() || !(reasons[o.id] ?? "").trim()}
                    busy={m.busy === o.id + v} onClick={() => decide(o.id, v)}>{label(v)}</Button>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
      <ErrorNote message={m.error} />
      <p className="mt-2 text-xs text-muted"><Landmark size={12} className="mr-1 inline" />A case passes only when every planned repetition in a qualifying run is adjudicated PASSED.</p>
    </Panel>
  );
}
