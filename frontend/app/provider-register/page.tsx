"use client";

import { Loader2 } from "lucide-react";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { getOperationsConnections } from "@/lib/api";

/** The AI and data providers this deployment is actually configured to use.
 * Due-diligence status stays "Not assessed" until the Provider Due Diligence
 * Register (ZL-T0-12) exists — nothing here claims a review that never ran. */
export default function ProviderRegisterPage() {
  const { data, error, loading, signedOut, reload } = useLiveData(
    "provider-register", (token, signal) => getOperationsConnections(token, signal), 20_000,
  );

  return (
    <PageShell
      title="Provider Register"
      subtitle="AI model and data providers configured in this deployment, and their due-diligence status."
      showMetrics={false}
    >
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      <div className="rounded-xl border border-line bg-soft p-3 mb-4 text-xs text-muted">
        &ldquo;Configured&rdquo; means the deployment has the credentials or endpoint for a provider. Provider due
        diligence (data class, region, retention, training opt-out) is <Pill>Not assessed</Pill> for every
        provider: the due-diligence register is not built yet.
      </div>
      {error || signedOut ? null : loading && !data ? (
        <div className="flex items-center justify-center py-12 text-muted">
          <Loader2 className="animate-spin mr-2" size={16} /> Reading provider configuration…
        </div>
      ) : data ? (
        <div className="space-y-4">
          <Card title="AI model providers">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] text-muted">
                  <th className="font-medium pb-2">Provider</th>
                  <th className="font-medium pb-2">Used for</th>
                  <th className="font-medium pb-2">Models</th>
                  <th className="font-medium pb-2">Status</th>
                  <th className="font-medium pb-2">Due diligence</th>
                </tr>
              </thead>
              <tbody>
                {data.modelProviders.map((p) => (
                  <tr key={p.key} className="border-t border-line align-top">
                    <td className="py-2.5 font-semibold text-ink">{p.name}</td>
                    <td className="py-2.5 pr-3 text-xs text-muted">{p.purpose}</td>
                    <td className="py-2.5 pr-3 text-xs text-ink">
                      {Object.values(p.models).length ? [...new Set(Object.values(p.models))].join(", ") : "—"}
                    </td>
                    <td className="py-2.5">
                      <Pill tone={p.configured ? "ok" : "neutral"}>{p.configured ? "Configured" : "Not configured"}</Pill>
                      {p.approved === false && p.configured && <Pill tone="warn">Not on approved list</Pill>}
                    </td>
                    <td className="py-2.5"><Pill>Not assessed</Pill></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
          <Card title="Data sources">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] text-muted">
                  <th className="font-medium pb-2">Source</th>
                  <th className="font-medium pb-2">Category</th>
                  <th className="font-medium pb-2">Access</th>
                  <th className="font-medium pb-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {data.dataSources.map((s) => (
                  <tr key={s.name} className="border-t border-line">
                    <td className="py-2 font-medium text-ink">{s.name}</td>
                    <td className="py-2 text-xs text-muted">{s.category}</td>
                    <td className="py-2 text-xs text-muted">{s.access}</td>
                    <td className="py-2"><Pill tone={s.configured ? "ok" : "neutral"}>{s.configured ? "Available" : "Not configured"}</Pill></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      ) : null}
    </PageShell>
  );
}
