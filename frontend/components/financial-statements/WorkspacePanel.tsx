"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Info, OctagonX } from "lucide-react";
import { Badge, Btn, ControlNote, DateCell, KeyGrid, Panel, SubTabs, inputClass, shortId, type Tone } from "@/components/workflow-ui/kit";
import {
  downloadPackage, getProvenance, getWorkspace, listPackages, type PackageSummary, type Provenance, type RailItem, type WorkspaceView,
} from "@/lib/financial-statements-api";

// Financial Statements Workspace — Document 02 (ZL-FSR-WF-002) screen FR-WF-001, areas 01–11.

export type WorkspaceStep = "intake" | "standards" | "statements";
type Filter = "ALL" | RailItem["severity"];

const SEVERITY: Record<RailItem["severity"], { label: string; tone: Tone; icon: typeof Info }> = {
  HARD_STOP: { label: "Hard stop", tone: "bad", icon: OctagonX },
  MATERIAL_REVIEW: { label: "Material review", tone: "warn", icon: AlertTriangle },
  INFORMATION: { label: "Information", tone: "info", icon: Info },
};
const RELEASE_TONE: Record<string, Tone> = { BLOCKED: "bad", DRAFT: "warn", "IN REVIEW": "info", APPROVED: "ok", PUBLISHED: "ok" };
const words = (s: string) => s.replace(/_/g, " ").toLowerCase();

/** Negative amounts in parentheses; a missing figure is "not supplied", never zero (§3 area 06). */
function amount(v: string | null | undefined) {
  if (v === null || v === undefined || v === "") return <span className="text-muted">not supplied</span>;
  const n = Number(v);
  if (!Number.isFinite(n)) return v;
  const text = Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 2 });
  return n < 0 ? <span aria-label={`minus ${text}`}>({text})</span> : text;
}

function Card({ id, title, action, children }: { id: string; title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section aria-label={title} className="rounded-xl border border-line bg-panel p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="text-[10px] font-bold uppercase tracking-wider text-muted"><span className="text-accent">{id}</span> {title}</h3>{action}
      </div>
      {children}
    </section>
  );
}

function ProvenanceDrawer({ data, onClose }: { data: Provenance; onClose: () => void }) {
  return (
    <section aria-label="Source drill-down" className="mt-3 rounded-xl border border-accent/40 bg-accent/5 p-3 text-[11px] text-ink">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-xs font-bold"><span className="text-accent">07</span> {data.statement_title}: {data.line.label} — {amount(data.line.amount)}</h4>
        <Btn variant="quiet" onClick={onClose}>Close</Btn>
      </div>
      <p className="mt-1 text-muted">{data.computation}</p>
      {data.accounts.length > 0 && (
        <table className="mt-2 w-full text-left">
          <thead className="text-muted"><tr><th scope="col" className="py-1">Account</th><th scope="col" className="text-right">Net debit</th><th scope="col">Mapping</th><th scope="col">Reviewer / evidence</th></tr></thead>
          <tbody>
            {data.accounts.map((a) => (
              <tr key={a.account_key} className="border-t border-line">
                <td className="py-1">{a.account_key} {a.account_name}<span className="block text-muted">{a.source_row}</span></td>
                <td className="text-right tabular-nums">{amount(a.balance)}</td>
                <td>{words(a.status)}{a.allocations.length ? ` · split ${a.allocations.map((x) => x.amount).join(" + ")}` : ""}</td>
                <td>{a.reviewer ?? "—"}{a.evidence_ref ? ` · ${a.evidence_ref}` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {data.journals.length > 0 && <p className="mt-2">Approved journals: {data.journals.map((j) => `${j.journal_id} (${words(j.correction_type)}, ${words(j.posting_status)})`).join("; ")}</p>}
      {data.supporting.length > 0 && <p className="mt-1">Supporting: {data.supporting.map((s) => `${words(s.kind)} ${s.filename} ${s.total ?? ""}`).join("; ")}</p>}
      <ControlNote>Layout {words(data.rule.layout)} · {data.rule.edition ?? "no edition"} · rule set {data.rule.ruleset} · source {data.source_file.filename} v{data.source_file.version}
        {" · "}{shortId("snap", (data.snapshot_hash ?? "").replace("sha256:", ""))} · line checksum {shortId("row", data.line_checksum.replace("sha256:", ""))}</ControlNote>
    </section>
  );
}

export function WorkspacePanel({ onOpen }: { onOpen: (step: WorkspaceStep) => void }) {
  const [list, setList] = useState<PackageSummary[]>([]);
  const [packageId, setPackageId] = useState("");
  const [view, setView] = useState<WorkspaceView | null>(null);
  const [tab, setTab] = useState("");
  const [filter, setFilter] = useState<Filter>("ALL");
  const [drawer, setDrawer] = useState<Provenance | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { listPackages().then(setList).catch(() => setList([])); }, []);

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
  function open(id: string) {
    setPackageId(id);
    setDrawer(null);
    if (id) void run(async () => { const next = await getWorkspace(id); setView(next); setTab(next.tabs[0]?.statement_id ?? "notes"); });
    else setView(null);
  }

  const current = view?.tabs.find((t) => t.statement_id === tab);
  const statement = view?.statements.find((s) => s.statement_id === tab);
  const rail = (view?.rail ?? []).filter((i) => filter === "ALL" || i.severity === filter);
  const hasPrior = !!statement?.lines.some((l) => l.prior !== null) || !!view?.source.prior_trial_balance_id;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="block min-w-64 text-[11px] font-semibold text-muted">Report package
          <select value={packageId} onChange={(e) => open(e.target.value)} className={`${inputClass} mt-1 text-xs`}>
            <option value="">Choose…</option>
            {list.filter((p) => p.state !== "SUPERSEDED").map((p) => <option key={p.id} value={p.id}>{p.entity || "Unnamed entity"} · v{p.version} · {words(p.state)}</option>)}
          </select>
        </label>
        <Btn variant="secondary" onClick={() => onOpen("statements")}>Assemble a package</Btn>
      </div>
      {error && <p role="alert" className="text-[11px] text-bad">{error}</p>}

      {!view ? <Panel title="Financial statements workspace" subtitle="One screen for scope, statements, validation, review and release">
        <p className="text-xs text-muted">Choose a report package, or assemble one from an approved trial balance and a frozen framework resolution.</p>
      </Panel> : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="min-w-0 space-y-4">
            {/* 03 Release status: text + icon + counts; announced politely */}
            <div role="status" aria-live="polite" className="rounded-xl border border-line bg-panel p-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={RELEASE_TONE[view.release_status] ?? "neutral"}>
                  {view.release_status === "APPROVED" ? <CheckCircle2 size={12} className="mr-1" /> : <OctagonX size={12} className="mr-1" />}{view.release_status}
                </Badge>
                <span className="text-xs font-semibold text-ink">{words(view.state)}</span>
                <span className="text-[11px] text-muted">{view.counts.HARD_STOP} hard stop · {view.counts.MATERIAL_REVIEW} review · {view.counts.INFORMATION} info</span>
              </div>
              <p className="mt-1 text-[11px] text-ink">{view.banner}</p>
            </div>

            <div className="grid gap-3 lg:grid-cols-3">
              <Card id="01" title="Entity and report scope" action={<Btn variant="quiet" onClick={() => onOpen("standards")}>Edit scope</Btn>}>
                <KeyGrid items={[["Entity", view.scope.entity || "Unknown"], ["Scope", words(view.scope.scope || "")],
                  ["Period", `${view.scope.period_start || "?"} – ${view.scope.period_end || "?"}`], ["Jurisdiction", view.scope.jurisdiction || "Not verified"]]} />
              </Card>
              <Card id="02" title="Framework" action={<Btn variant="quiet" onClick={() => onOpen("standards")}>Change</Btn>}>
                <KeyGrid items={[["Framework", view.framework.framework ? words(view.framework.framework) : "Determination required"],
                  ["Edition", view.framework.edition ?? "—"], ["Layout", words(view.framework.layout)],
                  ["Rule pack", view.framework.rule_pack ? words(view.framework.rule_pack.status) : "—"]]} />
                {view.framework.rules.length > 0 && (
                  <ul className="mt-2 space-y-0.5 text-[11px] text-ink">
                    {view.framework.rules.map((r) => <li key={r.rule_id}>{r.rule_id}: {words(r.outcome)} <span className="text-muted">({r.effective})</span>
                      {view.framework.citations[r.source] && <a href={view.framework.citations[r.source].url} target="_blank" rel="noreferrer" className="ml-1 text-info underline">[{r.source}]</a>}</li>)}
                  </ul>
                )}
              </Card>
              <Card id="11" title="Source package" action={<Btn variant="quiet" onClick={() => onOpen("intake")}>Open source</Btn>}>
                <KeyGrid items={[["Workbook", `${view.source.filename} · v${view.source.version}`], ["Hash", shortId("sha", view.source.sha256)],
                  ["Imported", <DateCell key="d" iso={view.source.imported_at} />], ["State", words(view.source.state)]]} />
              </Card>
            </div>

            <Panel title="What Kriton can tell you now" subtitle="From the recorded decisions only">
              <dl className="space-y-2 text-[11px]">
                {view.answers.map((a) => <div key={a.question}><dt className="font-semibold text-ink">{a.question}</dt><dd className="text-muted">{a.answer}</dd></div>)}
              </dl>
            </Panel>

            {/* 04 Statement tabs · 05 canonical statement · 06 comparative column · 07 drill-down */}
            <Panel title="Statements" subtitle="Tabs follow the resolved statement set; an omission keeps its legal basis">
              <SubTabs label="Statement" active={tab} onChange={(k) => { setTab(k); setDrawer(null); }}
                tabs={view.tabs.map((t) => ({ key: t.statement_id, label: t.status === "ASSEMBLED" ? t.title : `${t.title} (${words(t.status)})` }))} />
              <div className="mt-3">
                {tab === "notes" ? (
                  <ul className="space-y-1 text-[11px]">
                    {view.notes.map((n) => <li key={n.requirement_id} className="flex flex-wrap gap-2"><b>{n.requirement_id}</b>{n.title}<Badge tone={n.state === "SUPPORTED" || n.state === "NOT_APPLICABLE" ? "ok" : n.state === "REQUIRED_MISSING" ? "bad" : "warn"}>{words(n.state)}</Badge></li>)}
                  </ul>
                ) : current?.omission ? (
                  <p className="text-[11px] text-ink">Not presented — {words(current.status)}. Basis: {current.omission.basis || "recorded in the resolution"}.
                    {current.omission.approved_by ? ` Approved by ${current.omission.approved_by} (resolution revision ${current.omission.resolution_revision}).` : " Not yet approved."}</p>
                ) : statement && statement.lines.length ? (
                  <table className="w-full text-left text-[11px]">
                    <caption className="sr-only">{statement.title}, {view.scope.period_start} to {view.scope.period_end}</caption>
                    <thead className="text-muted"><tr><th scope="col" className="py-1">Line</th><th scope="col" className="text-right">Current period</th><th scope="col" className="text-right">Comparative</th></tr></thead>
                    <tbody>
                      {statement.lines.map((l) => (
                        <tr key={l.line_id} className={`border-t border-line ${l.kind !== "line" ? "font-semibold" : ""}`}>
                          <th scope="row" className="py-1 text-left font-[inherit]">
                            <button type="button" className="text-left hover:underline" onClick={() => run(async () => setDrawer(await getProvenance(view.package_id, statement.statement_id, l.line_id)))}>{l.label}</button>
                          </th>
                          <td className="text-right tabular-nums">{amount(l.amount)}</td>
                          <td className="text-right tabular-nums">{hasPrior ? amount(l.prior) : <span className="text-muted">not supplied</span>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : <p className="text-[11px] text-muted">{statement?.note || "Nothing to show."}{statement?.data_required?.length ? ` Needed: ${statement.data_required.join("; ")}.` : ""}</p>}
                {drawer && <ProvenanceDrawer data={drawer} onClose={() => setDrawer(null)} />}
              </div>
            </Panel>

            <div className="grid gap-3 lg:grid-cols-2">
              {/* 09 Review sequence */}
              <Card id="09" title="Review sequence" action={<Btn variant="quiet" onClick={() => onOpen("statements")}>Sign-off</Btn>}>
                <ol className="space-y-1 text-[11px] text-ink">
                  {view.review_sequence.map((r) => (
                    <li key={r.role} className="flex flex-wrap items-center gap-2">
                      <Badge tone={r.signed ? "ok" : r.available ? "neutral" : "warn"}>{r.signed ? "signed" : r.available ? "pending" : "not available"}</Badge>
                      <span className="font-semibold">{r.label}</span>
                      {r.signed && <span className="text-muted">{r.signed.by} · <DateCell iso={r.signed.at} /></span>}
                    </li>
                  ))}
                </ol>
              </Card>
              {/* 10 Export and release */}
              <Card id="10" title="Export and release">
                <div className="flex flex-wrap gap-2">
                  <Btn variant="secondary" busy={busy} disabled={!view.export.draft_allowed} title={view.export.draft_refusal.join(" ") || undefined}
                    onClick={() => run(() => downloadPackage(view.package_id, "json"))}>Preview draft</Btn>
                  <Btn variant="primary" disabled title={view.export.publish_reason}>Publish</Btn>
                </div>
                <p className="mt-2 text-[11px] text-muted">{view.export.draft_allowed ? "Drafts are watermarked DRAFT — NOT FOR STATUTORY USE." : `No draft: ${view.export.draft_refusal.join(" ")}`}</p>
                <p className="text-[11px] text-muted">{view.export.final_allowed ? "Final export allowed." : `Final release blocked (${view.export.final_reasons.length} reason(s)).`} {view.export.publish_reason}</p>
              </Card>
            </div>
          </div>

          {/* 08 Validation rail */}
          <aside aria-label="Validation rail" className="space-y-2 xl:sticky xl:top-4 xl:self-start">
            <div className="flex flex-wrap gap-1" role="group" aria-label="Filter findings">
              {(["ALL", "HARD_STOP", "MATERIAL_REVIEW", "INFORMATION"] as Filter[]).map((f) => (
                <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}
                  className={`rounded-md border px-2 py-1 text-[10px] font-bold ${filter === f ? "border-accent bg-accent/10 text-ink" : "border-line text-muted"}`}>
                  {f === "ALL" ? `All ${view.rail.length}` : `${SEVERITY[f].label} ${view.counts[f]}`}
                </button>
              ))}
            </div>
            <ul className="space-y-1.5">
              {rail.map((i) => {
                const S = SEVERITY[i.severity];
                return (
                  <li key={`${i.source}-${i.code}`} tabIndex={0} className="rounded-lg border border-line bg-panel p-2 text-[11px] text-ink focus:outline-accent">
                    <div className="flex flex-wrap items-center gap-1.5"><Badge tone={S.tone}><S.icon size={11} className="mr-1" />{S.label}</Badge><b>{words(i.code)}</b></div>
                    <p className="mt-1">{i.message}</p>
                    <p className="text-muted">{i.source} · {i.rule}</p>
                    <p className="text-muted">Action: {i.action}</p>
                  </li>
                );
              })}
            </ul>
          </aside>
        </div>
      )}
    </div>
  );
}
