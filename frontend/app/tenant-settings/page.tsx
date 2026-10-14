"use client";

import Link from "next/link";
import { Loader2 } from "lucide-react";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { getTenantSettings, type DeploymentSetting } from "@/lib/api";

function SettingValue({ value }: { value: DeploymentSetting["value"] }) {
  if (typeof value === "boolean") return <Pill tone={value ? "ok" : "neutral"}>{value ? "On" : "Off"}</Pill>;
  return <span className="font-semibold text-ink">{value}</span>;
}

function Settings({ title, rows }: { title: string; rows: DeploymentSetting[] }) {
  return (
    <Card title={title}>
      <ul className="divide-y divide-line">
        {rows.map((row) => (
          <li key={row.label} className="flex items-start justify-between gap-3 py-2.5">
            <span className="min-w-0">
              <span className="block text-sm text-ink">{row.label}</span>
              {row.note && <span className="block text-xs text-muted">{row.note}</span>}
            </span>
            <SettingValue value={row.value} />
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[11px] text-muted">Set per deployment in backend/.env (read-only here).</p>
    </Card>
  );
}

/** The workspace's real configuration: who is in it, and the security and
 * retention policy the backend is enforcing right now. */
export default function TenantSettingsPage() {
  const { data, error, loading, signedOut, reload } = useLiveData(
    "tenant-settings", (token, signal) => getTenantSettings(token, signal), 20_000,
  );

  return (
    <PageShell
      title="Tenant Settings"
      subtitle="Workspace details and the security and retention policy in force."
      showMetrics={false}
    >
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {error || signedOut ? null : loading && !data ? (
        <div className="flex items-center justify-center py-12 text-muted">
          <Loader2 className="animate-spin mr-2" size={16} /> Loading settings…
        </div>
      ) : data ? (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <Card title="Workspace">
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
              <dt className="text-muted">Name</dt><dd className="text-ink">{data.workspace.name || "—"}</dd>
              <dt className="text-muted">People</dt>
              <dd className="text-ink">{data.people.active} active · {data.people.inactive} inactive</dd>
              <dt className="text-muted">Service accounts</dt><dd className="text-ink">{data.people.serviceAccounts}</dd>
            </dl>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {Object.entries(data.people.byRole).map(([role, count]) => (
                <Pill key={role}>{role}: {count}</Pill>
              ))}
            </div>
            <Link href="/users-teams" className="mt-3 inline-block text-xs font-semibold text-brand hover:underline">
              Manage users
            </Link>
          </Card>
          <Settings title="Security policy" rows={data.security} />
          <Settings title="Data retention" rows={data.retention} />
        </div>
      ) : null}
    </PageShell>
  );
}
