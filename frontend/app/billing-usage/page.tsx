"use client";

import { CreditCard, Loader2 } from "lucide-react";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { getUsage } from "@/lib/api";

/** Real usage measured from this workspace's records. Billing is shown as
 * not connected rather than with sample invoices: no billing system exists. */
export default function BillingUsagePage() {
  const { data, error, loading, signedOut, reload } = useLiveData(
    "billing-usage", (token, signal) => getUsage(token, signal), 20_000,
  );
  const peak = Math.max(1, ...(data?.questionsByMonth.map((m) => m.questions) ?? [1]));

  return (
    <PageShell
      title="Billing & Usage"
      subtitle="Usage measured from this workspace. Visible to Admin roles only."
      showMetrics={false}
    >
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {error || signedOut ? null : loading && !data ? (
        <div className="flex items-center justify-center py-12 text-muted">
          <Loader2 className="animate-spin mr-2" size={16} /> Measuring usage…
        </div>
      ) : data ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {[
              { label: "Kriton questions this month", value: data.totals.questions_this_month },
              { label: "Active users this month", value: data.totals.active_users_this_month },
              { label: "Questions all time", value: data.totals.questions_all_time },
              { label: "Documents uploaded", value: data.totals.documents },
              { label: "Saved answers", value: data.totals.saved_answers },
              { label: "Drafts", value: data.totals.drafts },
              { label: "Generated files", value: data.totals.generated_files },
            ].map((stat) => (
              <div key={stat.label} className="rounded-xl border border-line bg-panel p-4">
                <span className="block text-2xl font-semibold text-ink">{stat.value.toLocaleString()}</span>
                <span className="block text-xs text-muted">{stat.label}</span>
              </div>
            ))}
          </div>

          <Card title="Kriton questions per month">
            <div className="flex h-40 items-end gap-3" role="list" aria-label="Questions per month">
              {data.questionsByMonth.map((m) => (
                <div key={m.month} role="listitem" className="flex flex-1 flex-col items-center gap-1"
                  aria-label={`${m.label}: ${m.questions} questions`}>
                  <span className="text-xs text-ink">{m.questions}</span>
                  <div className="w-full rounded-t bg-brand/70" style={{ height: `${(m.questions / peak) * 100}%`, minHeight: m.questions ? 4 : 0 }} />
                  <span className="text-[11px] text-muted">{m.label}</span>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Billing">
            <p className="flex items-start gap-2 text-sm text-muted">
              <CreditCard size={16} className="mt-0.5 shrink-0" />
              {data.billing.reason}
            </p>
          </Card>
        </div>
      ) : null}
    </PageShell>
  );
}
