"use client";

import { Fragment, useState } from "react";
import { ESCALATIONS } from "@/lib/governance-data";
import { Pill } from "./Pill";

export function EscalationTable({ defaultExpandedId = "ESC-1842" }: { defaultExpandedId?: string }) {
  const [openId, setOpenId] = useState<string | null>(defaultExpandedId);

  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-[11px] text-muted">
          <th className="font-medium pb-2">Item</th>
          <th className="font-medium pb-2">Topic</th>
          <th className="font-medium pb-2">Risk</th>
          <th className="font-medium pb-2">Jurisdiction</th>
          <th className="font-medium pb-2">SLA</th>
          <th className="font-medium pb-2" />
        </tr>
      </thead>
      <tbody>
        {ESCALATIONS.map((e) => {
          const isOpen = openId === e.id;
          return (
            <Fragment key={e.id}>
              <tr className="border-t border-line align-top">
                <td className="py-2.5 font-semibold text-ink">{e.id}</td>
                <td className="py-2.5 text-ink">
                  {e.topic}
                  <div className="text-[11px] text-muted">{e.status}</div>
                </td>
                <td className="py-2.5">
                  <Pill tone={e.risk === "Restricted" ? "bad" : "warn"}>{e.risk}</Pill>
                </td>
                <td className="py-2.5 text-ink">{e.jurisdiction}</td>
                <td className={`py-2.5 ${e.sla === "Overdue" ? "font-semibold text-bad" : "text-ink"}`}>{e.sla}</td>
                <td className="py-2.5 text-right">
                  <button
                    onClick={() => setOpenId(isOpen ? null : e.id)}
                    className="rounded-lg border border-line bg-panel px-2.5 py-1 text-xs font-medium text-ink hover:bg-soft"
                  >
                    {isOpen ? "Close" : "Open"}
                  </button>
                </td>
              </tr>
              {isOpen && (
                <tr>
                  <td colSpan={6} className="pb-3">
                    <div className="rounded-xl border border-line bg-soft p-3.5 text-sm text-ink leading-relaxed">
                      <span className="font-semibold">Decision workspace:</span> {e.detail}
                      <div className="mt-2.5 flex flex-wrap gap-1.5">
                        <Pill>Source bundle</Pill>
                        <Pill>Risk decision</Pill>
                        <Pill>Audit log</Pill>
                        <Pill>Maker-checker required</Pill>
                      </div>
                    </div>
                  </td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}
