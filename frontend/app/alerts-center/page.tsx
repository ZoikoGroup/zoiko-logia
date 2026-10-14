"use client";

import Link from "next/link";
import { ArrowRight, BellRing, CheckCircle2, Loader2 } from "lucide-react";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { getOperationsAlerts } from "@/lib/api";

const SEVERITY_TONE: Record<string, "bad" | "warn" | "info" | "neutral"> = {
  Critical: "bad",
  High: "bad",
  Medium: "warn",
  Low: "info",
};

/** Live governance exceptions for this workspace — the same list the
 * Governance Dashboard shows. Each alert links to where it is resolved. */
export default function AlertsCenterPage() {
  const { data, error, loading, signedOut, reload } = useLiveData(
    "alerts-center", (token, signal, fresh) => getOperationsAlerts(token, signal, fresh), 30_000,
  );
  const alerts = data?.alerts ?? [];

  return (
    <PageShell
      title="Alerts Center"
      subtitle="Live exceptions from incidents, escalations, evaluations, reviews and source licences."
      showMetrics={false}
    >
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {error || signedOut ? null : loading && !data ? (
        <div className="flex items-center justify-center py-12 text-muted">
          <Loader2 className="animate-spin mr-2" size={16} /> Checking for alerts…
        </div>
      ) : alerts.length === 0 ? (
        <Card>
          <p className="flex items-center justify-center gap-2 py-6 text-sm text-muted">
            <CheckCircle2 size={16} className="text-ok" /> No active alerts in this workspace.
          </p>
        </Card>
      ) : (
        <Card title={`Active alerts (${alerts.length})`}>
          <ul className="divide-y divide-line">
            {alerts.map((alert) => (
              <li key={alert.id} className="flex flex-wrap items-start gap-3 py-3">
                <BellRing size={16} className="mt-0.5 shrink-0 text-warn" />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Pill tone={SEVERITY_TONE[alert.severity] ?? "neutral"}>{alert.severity}</Pill>
                    <span className="text-sm font-semibold text-ink">{alert.title}</span>
                  </div>
                  <p className="mt-1 text-xs text-muted">{alert.domain}{alert.detail ? ` · ${alert.detail}` : ""}</p>
                </div>
                <Link href={alert.href} className="inline-flex items-center gap-1 text-xs font-semibold text-brand hover:underline">
                  Resolve <ArrowRight size={12} />
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </PageShell>
  );
}
