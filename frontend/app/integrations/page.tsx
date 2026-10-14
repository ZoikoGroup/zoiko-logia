"use client";

import { Loader2, Plug } from "lucide-react";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { getOperationsConnections } from "@/lib/api";

/** Systems this deployment is wired to, read from its configuration.
 * Whether each one is reachable right now is on Status & Health. */
export default function IntegrationsPage() {
  const { data, error, loading, signedOut, reload } = useLiveData(
    "integrations", (token, signal) => getOperationsConnections(token, signal), 20_000,
  );
  const integrations = data?.integrations ?? [];
  const configured = integrations.filter((i) => i.configured).length;

  return (
    <PageShell
      title="Integrations"
      subtitle="Connected systems this deployment uses. Live reachability is on Status & Health."
      showMetrics={false}
    >
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {error || signedOut ? null : loading && !data ? (
        <div className="flex items-center justify-center py-12 text-muted">
          <Loader2 className="animate-spin mr-2" size={16} /> Reading integrations…
        </div>
      ) : (
        <Card title={`Integrations (${configured} of ${integrations.length} configured)`}>
          <ul className="divide-y divide-line">
            {integrations.map((integration) => (
              <li key={integration.name} className="flex items-center justify-between gap-3 py-2.5">
                <span className="flex min-w-0 items-center gap-2.5">
                  <Plug size={15} className="shrink-0 text-brand" />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium text-ink">{integration.name}</span>
                    <span className="block text-xs text-muted">
                      {integration.purpose}{integration.detail ? ` · ${integration.detail}` : ""}
                    </span>
                  </span>
                </span>
                <Pill tone={integration.configured ? "ok" : "neutral"}>
                  {integration.configured ? "Configured" : "Not configured"}
                </Pill>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </PageShell>
  );
}
