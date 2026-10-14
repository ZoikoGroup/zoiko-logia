"use client";

import { Loader2 } from "lucide-react";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { getRolesMatrix } from "@/lib/api";

/** The permission registry the backend actually enforces, with how many
 * active people in this workspace hold each role. */
export default function RolesPermissionsPage() {
  const { data, error, loading, signedOut, reload } = useLiveData(
    "roles-permissions", (token, signal) => getRolesMatrix(token, signal), 20_000,
  );

  return (
    <PageShell
      title="Roles & Permissions"
      subtitle="What each role can do, exactly as the backend enforces it. Assign roles in Users & Teams."
      showMetrics={false}
    >
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {error || signedOut ? null : loading && !data ? (
        <div className="flex items-center justify-center py-12 text-muted">
          <Loader2 className="animate-spin mr-2" size={16} /> Loading roles…
        </div>
      ) : data ? (
        <div className="space-y-4">
          {data.unrecognisedRoles.length > 0 && (
            <p role="alert" className="rounded-lg border border-warn/30 bg-warn/10 px-3 py-2 text-sm text-ink">
              {data.unrecognisedRoles.map((r) => `${r.activeUsers} user(s) with role "${r.name}"`).join(", ")} —
              this role has no permissions. Give them a real role in Users &amp; Teams.
            </p>
          )}
          <Card title="Roles">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] text-muted">
                  <th className="font-medium pb-2">Role</th>
                  <th className="font-medium pb-2">Purpose</th>
                  <th className="font-medium pb-2">Permissions</th>
                  <th className="font-medium pb-2 text-right">Active users</th>
                </tr>
              </thead>
              <tbody>
                {data.roles.map((role) => (
                  <tr key={role.name} className="border-t border-line align-top">
                    <td className="py-2.5 pr-3 font-semibold text-ink whitespace-nowrap">{role.name}</td>
                    <td className="py-2.5 pr-3 text-xs text-muted">{role.purpose}</td>
                    <td className="py-2.5 pr-3">
                      {role.permissions.length === 0 ? (
                        <span className="text-xs text-muted">No governance permissions</span>
                      ) : (
                        <span className="flex flex-wrap gap-1">
                          {role.permissions.map((p) => <Pill key={p}>{p}</Pill>)}
                        </span>
                      )}
                    </td>
                    <td className="py-2.5 text-right text-ink">{role.activeUsers}</td>
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
