"use client";

import { Activity, Loader2 } from "lucide-react";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { getOperationsStatus, type StatusCheck } from "@/lib/api";

const STATE: Record<StatusCheck["state"], { label: string; tone: "ok" | "bad" | "neutral" }> = {
  operational: { label: "Operational", tone: "ok" },
  down: { label: "Down", tone: "bad" },
  not_configured: { label: "Not configured", tone: "neutral" },
};

/** Live checks against each service this backend depends on, run each time
 * the page loads (and every minute while it is open). */
export default function StatusHealthPage() {
  const { data, error, loading, signedOut, reload } = useLiveData(
    "status-health", (token, signal) => getOperationsStatus(token, signal), 30_000,
  );
  const checks = data?.checks ?? [];
  const down = checks.filter((c) => c.state === "down").length;
  const operational = checks.filter((c) => c.state === "operational").length;

  return (
    <PageShell
      title="Status & Health"
      subtitle="Live checks of the database, authentication, search, diagrams, background jobs, audit ledger and AI providers."
      showMetrics={false}
    >
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {error || signedOut ? null : loading && !data ? (
        <div className="flex items-center justify-center py-12 text-muted">
          <Loader2 className="animate-spin mr-2" size={16} /> Running health checks…
        </div>
      ) : (
        <Card title="Services">
          <p className={`mb-3 text-sm font-semibold ${down ? "text-bad" : "text-ok"}`}>
            {down ? `${down} service${down === 1 ? "" : "s"} down` : "All configured services operational"}
            <span className="font-normal text-muted"> · {operational} operational · checked{" "}
              {data ? new Date(data.checkedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : ""}
            </span>
          </p>
          <ul className="divide-y divide-line">
            {checks.map((check) => (
              <li key={check.name} className="flex items-center justify-between gap-3 py-2.5">
                <span className="flex min-w-0 items-center gap-2.5">
                  <Activity size={15} className="shrink-0 text-brand" />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium text-ink">{check.name}</span>
                    <span className="block text-xs text-muted">{check.detail}</span>
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  {check.latencyMs !== null && <span className="text-xs text-muted">{check.latencyMs} ms</span>}
                  <Pill tone={STATE[check.state].tone}>{STATE[check.state].label}</Pill>
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </PageShell>
  );
}
