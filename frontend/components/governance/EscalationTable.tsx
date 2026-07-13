"use client";

import { Fragment, useEffect, useState } from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { getEscalations, type Escalation } from "@/lib/safety-api";
import { Pill } from "./Pill";

const RISK_TONE: Record<string, "ok" | "info" | "warn" | "bad"> = {
  LOW: "ok",
  MEDIUM: "info",
  HIGH: "warn",
  RESTRICTED: "bad",
};

function formatSla(deadline: string | null): { label: string; overdue: boolean } {
  if (!deadline) return { label: "—", overdue: false };
  const ms = new Date(deadline).getTime() - Date.now();
  if (ms <= 0) return { label: "Overdue", overdue: true };
  const hours = Math.floor(ms / (60 * 60 * 1000));
  const mins = Math.floor((ms % (60 * 60 * 1000)) / (60 * 1000));
  return { label: hours > 0 ? `${hours}h ${mins}m` : `${mins}m`, overdue: false };
}

export function EscalationTable({ limit = 5 }: { limit?: number }) {
  const [escalations, setEscalations] = useState<Escalation[]>([]);
  const [loading, setLoading] = useState(true);
  const [openId, setOpenId] = useState<string | null>(null);

  useEffect(() => {
    getEscalations()
      .then((rows) => setEscalations(rows.filter((r) => r.status !== "RESOLVED" && r.status !== "REFUSED")))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-10 text-muted">
        <Loader2 className="animate-spin mr-2" size={16} /> Loading escalations…
      </div>
    );
  }

  if (escalations.length === 0) {
    return <p className="text-sm text-muted py-4">No active escalations.</p>;
  }

  const rows = escalations.slice(0, limit);

  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-[11px] text-muted">
          <th className="font-medium pb-2 pr-3">Item</th>
          <th className="font-medium pb-2 pr-3">Topic</th>
          <th className="font-medium pb-2 pr-3">Risk</th>
          <th className="font-medium pb-2 pr-3">Jurisdiction</th>
          <th className="font-medium pb-2 pr-3">SLA</th>
          <th className="font-medium pb-2" />
        </tr>
      </thead>
      <tbody>
        {rows.map((e) => {
          const isOpen = openId === e.id;
          const sla = formatSla(e.sla_deadline);
          return (
            <Fragment key={e.id}>
              <tr className="border-t border-line align-top">
                <td className="py-2.5 pr-3 font-semibold text-ink whitespace-nowrap">{e.id}</td>
                <td className="py-2.5 pr-3 text-ink">
                  {e.topic}
                  <div className="text-[11px] text-muted">{e.status}</div>
                </td>
                <td className="py-2.5 pr-3">
                  <Pill tone={RISK_TONE[e.risk_level] ?? "neutral"}>{e.risk_level}</Pill>
                </td>
                <td className="py-2.5 pr-3 text-ink whitespace-nowrap">{e.jurisdiction}</td>
                <td className={`py-2.5 pr-3 whitespace-nowrap ${sla.overdue ? "font-semibold text-bad" : "text-ink"}`}>{sla.label}</td>
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
                      <span className="font-semibold">Route reason:</span> {e.route_reason ?? "—"}
                      {e.detail && <p className="mt-1.5 text-xs text-muted">{e.detail}</p>}
                      <Link
                        href={`/audit-replay?correlation_id=${encodeURIComponent(e.query_id)}`}
                        className="mt-2 inline-block text-xs text-brand hover:underline"
                      >
                        View audit trail
                      </Link>
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
