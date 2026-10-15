"use client";

import { useState } from "react";
import { Button, GATE_STYLE, humanize, inputClass, utcDate } from "@/components/operations/ui";
import type { Gate, GateStatus } from "@/lib/api";

/** Assurance-gate list, gate editor and change history shared by the
 * Provider Register and Integrations pages. */

export function GateList({ gates, title }: { gates: Gate[]; title: string }) {
  return (
    <div>
      <h4 className="mb-2 font-bold text-ink">{title}</h4>
      <ul className="space-y-2">
        {gates.map((g) => {
          const s = GATE_STYLE[g.status];
          return (
            <li key={g.key} className={`flex items-start justify-between gap-3 rounded-lg border p-2.5 ${s.row}`}>
              <span className="flex items-start gap-2">
                <s.icon size={16} className={`mt-0.5 shrink-0 ${s.tone}`} />
                <span><span className="block text-sm font-semibold text-ink">{g.label}{g.derived && <span className="ml-1 text-[10px] font-normal text-muted">(derived)</span>}</span>
                  <span className="block text-xs text-muted">{g.note || g.description}</span></span>
              </span>
              <span className={`text-xs font-bold ${s.tone}`}>{s.label}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function GateEditor({ gates, canEdit, onSave, busy }: {
  gates: Gate[]; canEdit: boolean; busy: string; onSave: (key: string, status: GateStatus, note: string) => void;
}) {
  const [drafts, setDrafts] = useState<Record<string, { status: GateStatus; note: string }>>({});
  return (
    <ul className="space-y-3">
      {gates.map((g) => {
        const d = drafts[g.key] ?? { status: g.status, note: g.note ?? "" };
        const changed = d.status !== g.status || d.note !== (g.note ?? "");
        return (
          <li key={g.key} className="rounded-lg border border-line p-3">
            <p className="text-sm font-semibold text-ink">{g.label}</p>
            <p className="mb-2 text-xs text-muted">{g.description}{g.byName ? ` · last set by ${g.byName}` : ""}</p>
            {g.derived ? <p className="text-xs text-muted">Derived: {g.note}</p> : (
              <div className="grid gap-2 sm:grid-cols-[8rem_minmax(0,1fr)_auto]">
                <select aria-label={`${g.label} status`} className={inputClass} disabled={!canEdit} value={d.status}
                  onChange={(e) => setDrafts({ ...drafts, [g.key]: { ...d, status: e.target.value as GateStatus } })}>
                  <option value="pass">Pass</option><option value="open">Open</option><option value="fail">Fail</option>
                </select>
                <input className={inputClass} disabled={!canEdit} placeholder="Evidence or reason" value={d.note}
                  onChange={(e) => setDrafts({ ...drafts, [g.key]: { ...d, note: e.target.value } })} />
                {canEdit && <Button disabled={!changed} busy={busy === `gate-${g.key}`} onClick={() => onSave(g.key, d.status, d.note)}>Save</Button>}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function History({ entries }: { entries: { at: string; action: string; actor: string; note: string }[] }) {
  return (
    <ol className="space-y-3 border-l border-line pl-4 text-sm">
      {[...entries].reverse().map((h, i) => (
        <li key={`${h.at}-${i}`}>
          <p className="font-semibold text-ink">{humanize(h.action.replace(":", ": "))} <span className="font-normal text-muted">· {h.actor}</span></p>
          <p className="text-xs text-muted">{utcDate(h.at)}</p>
          {h.note && <p className="text-ink">{h.note}</p>}
        </li>
      ))}
    </ol>
  );
}


/** A list of pass / open / fail checks with an explanation each. */
export function ChecksList({ title, checks }: { title?: string; checks: { label: string; status: GateStatus; note?: string; detail?: string }[] }) {
  return (
    <div>
      {title && <h4 className="mb-2 font-bold text-ink">{title}</h4>}
      <ul className="divide-y divide-line">
        {checks.map((c) => {
          const s = GATE_STYLE[c.status];
          return (
            <li key={c.label} className="flex items-start justify-between gap-3 py-2">
              <span className="flex items-start gap-2">
                <s.icon size={16} className={`mt-0.5 shrink-0 ${s.tone}`} />
                <span><span className="block text-sm font-semibold text-ink">{c.label}</span>
                  {(c.note || c.detail) && <span className="block text-xs text-muted">{c.note || c.detail}</span>}</span>
              </span>
              <span className={`text-xs font-bold uppercase ${s.tone}`}>{s.label}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
