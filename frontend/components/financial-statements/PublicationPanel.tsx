"use client";

import { useEffect, useState } from "react";
import { Badge, Btn, Callout, ControlNote, DateCell, KeyGrid, Panel, inputClass, shortId, type Tone } from "@/components/workflow-ui/kit";
import {
  downloadArtifact, getPublication, issuePublication, listPackages, previewPublication, reimportWord, renderPublication, submitFiling,
  type PackageSummary, type PublicationModel, type PublicationOverview,
} from "@/lib/financial-statements-api";

// Publication and filing workspace — Document 06 (ZL-FSR-ENG-006) wireframe FP-001, markers 01–06.

const CHANNELS: [string, string][] = [["html", "Web (HTML)"], ["docx", "Word"], ["pdf", "PDF"], ["xlsx", "Excel workbook"]];
const STATE_TONE: Record<string, Tone> = { WORKING_DRAFT: "warn", VALIDATED_DRAFT: "info", REVIEW_APPROVED: "info",
  AUTHORISED_FOR_ISSUE: "ok", ISSUED: "ok", SUPERSEDED: "neutral" };
const words = (s: string) => s.replace(/_/g, " ").toLowerCase();

function Preview({ model }: { model: PublicationModel }) {
  return (
    <div className="space-y-3 text-[11px]">
      <p className="rounded-md border-2 border-accent px-2 py-1 font-bold text-ink">{model.status_label}</p>
      <div><p className="text-sm font-bold text-ink">{model.masthead.entity}</p>
        <p className="text-muted">{model.audience_title} · {model.masthead.period_start} – {model.masthead.period_end} · {model.masthead.edition ?? model.masthead.framework ?? "framework not resolved"} · amounts in {model.unit_label}</p></div>
      {model.statements.map((s) => (
        <div key={s.statement_id}>
          <h4 className="font-bold text-ink">{s.title}</h4>
          {s.lines.length ? (
            <table className="w-full text-left">
              <caption className="sr-only">{s.title}</caption>
              <thead className="text-muted"><tr><th scope="col">Line</th><th scope="col" className="text-right">Current</th><th scope="col" className="text-right">Prior</th></tr></thead>
              <tbody>{s.lines.map((l) => (
                <tr key={l.concept_id} className={`border-t border-line ${l.kind !== "line" ? "font-semibold" : ""}`}>
                  <th scope="row" className="py-0.5 text-left font-[inherit]">{l.label}</th>
                  <td className="text-right tabular-nums">{l.display}</td><td className="text-right tabular-nums text-muted">{l.prior_display}</td>
                </tr>
              ))}</tbody>
            </table>
          ) : <p className="text-muted">{s.note || words(s.status)}</p>}
        </div>
      ))}
      {model.omitted.map((o) => <p key={o.statement_id} className="text-muted">Omitted: {words(o.statement_id)} — {o.basis}</p>)}
      {model.notes.length > 0 && <div><h4 className="font-bold text-ink">Notes</h4>
        {model.notes.map((n) => <p key={n.requirement_id}><b>{n.number ?? "—"}. {n.title}</b> {n.text}</p>)}</div>}
      {model.rounding.map((r) => <p key={r} className="text-muted">{r}</p>)}
      {model.analysis && <div className="rounded-md border border-line p-2"><h4 className="font-bold">{model.analysis.label}</h4>
        {model.analysis.measures.map((m) => <p key={m.name}>{m.name}: {m.value ?? "not available"} <span className="text-muted">({m.definition})</span></p>)}</div>}
    </div>
  );
}

export function PublicationPanel() {
  const [list, setList] = useState<PackageSummary[]>([]);
  const [packageId, setPackageId] = useState("");
  const [view, setView] = useState<PublicationOverview | null>(null);
  const [audience, setAudience] = useState("member_accounts");
  const [scale, setScale] = useState("units");
  const [model, setModel] = useState<PublicationModel | null>(null);
  const [destination, setDestination] = useState("UK_COMPANIES_HOUSE");
  const [confirmed, setConfirmed] = useState(false);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { listPackages().then(setList).catch(() => setList([])); }, []);

  async function run(call: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await call();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The request failed.");
    } finally {
      setBusy(false);
    }
  }
  async function refresh(id = packageId, aud = audience, sc = scale) {
    const [overview, preview] = await Promise.all([getPublication(id), previewPublication(id, aud, sc)]);
    setView(overview);
    setModel(preview.model);
  }
  function choose(id: string) {
    setPackageId(id);
    setView(null);
    setModel(null);
    if (id) void run(() => refresh(id));
  }

  const current = view?.audiences.find((a) => a.key === audience);
  const artifacts = (view?.artifacts ?? []).filter((a) => a.audience === audience);
  const latestIssue = view?.issues.find((i) => i.audience === audience);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="block min-w-64 text-[11px] font-semibold text-muted">Report package
          <select value={packageId} onChange={(e) => choose(e.target.value)} className={`${inputClass} mt-1 text-xs`}>
            <option value="">Choose…</option>
            {list.filter((p) => p.state !== "SUPERSEDED").map((p) => <option key={p.id} value={p.id}>{p.entity || "Unnamed entity"} · v{p.version}</option>)}
          </select>
        </label>
        {/* 02 Framework and audience profile */}
        <label className="block text-[11px] font-semibold text-muted">Audience
          <select value={audience} disabled={!view} onChange={(e) => { setAudience(e.target.value); void run(() => refresh(packageId, e.target.value, scale)); }} className={`${inputClass} mt-1 text-xs`}>
            {(view?.audiences ?? [{ key: "member_accounts", title: "Annual report and financial statements" }]).map((a) => <option key={a.key} value={a.key}>{a.title}</option>)}
          </select>
        </label>
        <label className="block text-[11px] font-semibold text-muted">Scale
          <select value={scale} disabled={!view} onChange={(e) => { setScale(e.target.value); void run(() => refresh(packageId, audience, e.target.value)); }} className={`${inputClass} mt-1 text-xs`}>
            <option value="units">£</option><option value="thousands">£000</option>
          </select>
        </label>
      </div>
      {error && <p role="alert" className="text-[11px] text-bad">{error}</p>}

      {!view ? <Panel title="Publish" subtitle="Rendering, issue and filing from the approved report model">
        <p className="text-xs text-muted">Choose a report package.</p>
      </Panel> : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
          <div className="min-w-0 space-y-4">
            {/* 01 Workspace header */}
            <Panel title={`${view.entity || "Entity"} · package v${view.package_version}`} subtitle={view.framework ?? "Framework not resolved"}>
              <KeyGrid items={[["Publication state", <Badge key="s" tone={STATE_TONE[view.state] ?? "neutral"}>{words(view.state)}</Badge>],
                ["Assurance", view.assurance_status ? words(view.assurance_status) : "not run"], ["Release", view.release_id ?? "none"],
                ["Audience matrix", `${view.audience_matrix.id} · ${words(view.audience_matrix.status)}`]]} />
            </Panel>
            {/* 03 Release warning */}
            <div role="status" aria-live="polite">
              <Callout tone={current?.issue_blockers.length || view.misleading.length ? "warn" : "ok"}
                title={current?.issue_blockers.length ? `${current.issue_blockers.length} reason(s) issue is blocked` : "Issue prerequisites met"}>
                {[...view.misleading, ...(current?.issue_blockers ?? []), ...(model?.blockers ?? [])].map((r) => <span key={r} className="block">{r}</span>)}
              </Callout>
            </div>
            {/* 04 Read-only legal-format preview */}
            <Panel title="Preview" subtitle="Read-only projection of the approved facts — not a new calculation">
              {model ? <Preview model={model} /> : <p className="text-xs text-muted">Loading…</p>}
            </Panel>
          </div>

          <aside className="space-y-4">
            {/* 05 Channel gallery */}
            <Panel title="Channels" subtitle="Each file is read back and compared with the approved model">
              <div className="flex flex-wrap gap-1.5">
                {CHANNELS.map(([c, label]) => <Btn key={c} busy={busy} onClick={() => run(async () => { await renderPublication(packageId, { audience, channel: c, scale }); await refresh(); })}>{label}</Btn>)}
              </div>
              <ul className="mt-2 space-y-1.5 text-[11px]">
                {artifacts.map((a) => (
                  <li key={a.id} className="rounded-lg border border-line p-2">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge tone={a.kind === "EXTERNAL_EDIT" ? "warn" : a.validation.parity?.ok ? "ok" : "bad"}>{a.kind === "EXTERNAL_EDIT" ? "quarantined" : a.validation.parity?.ok ? "parity ok" : "parity failed"}</Badge>
                      <b>{a.channel.toUpperCase()}</b><span className="text-muted">{words(a.state)} · {a.scale}</span>
                    </div>
                    <p className="text-muted">sha256 {a.sha256.slice(0, 12)}… · <DateCell iso={a.created_at} /></p>
                    {a.validation.parity && !a.validation.parity.ok && <p className="text-bad">{a.validation.parity.issues.slice(0, 2).join(" ")}</p>}
                    {a.validation.sensitive && !a.validation.sensitive.ok && <p className="text-bad">Internal content: {a.validation.sensitive.hits.join(", ")}</p>}
                    {a.validation.accessibility && !a.validation.accessibility.ok && <p className="text-bad">Accessibility: {a.validation.accessibility.failed.join(", ")}</p>}
                    {a.validation.diff && <p className="text-muted">{a.validation.diff.length} change(s): {a.validation.diff.slice(0, 2).join("; ")}</p>}
                    <div className="mt-1 flex flex-wrap gap-2">
                      <button type="button" className="text-info underline" onClick={() => run(() => downloadArtifact(a.id, a.filename))}>Download</button>
                      {a.channel === "docx" && a.kind === "RENDER" && (
                        <label className="cursor-pointer text-info underline">Re-import edited Word
                          <input type="file" accept=".docx" className="sr-only" onChange={(e) => { const f = e.target.files?.[0]; if (f) void run(async () => { await reimportWord(a.id, f); await refresh(); }); }} />
                        </label>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </Panel>
            {/* 06 Release controls */}
            <Panel title="Issue and filing" subtitle="Separate review, issue and transmission states">
              <Btn variant="success" busy={busy} disabled={!!current?.issue_blockers.length} title={current?.issue_blockers.join(" ") || undefined}
                onClick={() => run(async () => { await issuePublication(packageId, audience, scale); await refresh(); })}>Issue this audience</Btn>
              {latestIssue && <p className="mt-2 text-[11px] text-ink">Issued {latestIssue.release_id} by {latestIssue.issued_by} · <DateCell iso={latestIssue.issued_at} /></p>}
              {latestIssue && (
                <div className="mt-2 grid gap-1.5 text-[11px]">
                  <select aria-label="Filing destination" value={destination} onChange={(e) => setDestination(e.target.value)} className={`${inputClass} text-xs`}>
                    {Object.entries(view.adapters).map(([k, a]) => <option key={k} value={k}>{a.title} — {words(a.status)}</option>)}
                  </select>
                  <label className="flex items-center gap-1"><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />I confirm this submission</label>
                  <Btn busy={busy} onClick={() => run(async () => {
                    try { await submitFiling(latestIssue.id, { destination, live: true, confirmed }); } catch (e) { setMessage(e instanceof Error ? e.message : "Refused"); }
                    await refresh();
                  })}>Submit filing</Btn>
                  {message && <p role="alert" className="text-accent-ink">{message}</p>}
                  {latestIssue.filing.map((f, i) => <p key={i} className="text-muted">{words(f.destination)}: {words(f.status)} — {f.reasons[0]}</p>)}
                </div>
              )}
            </Panel>
            <Panel title="Filing capability" subtitle="No adapter is certified; nothing is transmitted">
              <ul className="space-y-1 text-[11px]">
                {Object.entries(view.adapters).map(([k, a]) => <li key={k}><Badge tone="neutral">{words(a.status)}</Badge> {a.title}</li>)}
                {Object.entries(view.taxonomies).map(([k, t]) => <li key={k}><Badge tone="warn">{t.installed ? "installed" : "not installed"}</Badge> {t.title} <span className="text-muted">· {t.licence}</span></li>)}
              </ul>
              <ul className="mt-2 list-disc pl-4 text-[11px] text-muted">{view.audience_matrix.notes.map((n) => <li key={n}>{n}</li>)}</ul>
            </Panel>
            <ControlNote>A downloaded file is not filed accounts. Model {model ? shortId("m", model.model_hash.replace("sha256:", "")) : "—"}.</ControlNote>
          </aside>
        </div>
      )}
    </div>
  );
}
