"use client";

import { useEffect, useState } from "react";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { getAuthToken, listRoles, Role } from "@/lib/api";

export default function RolesPermissionsPage() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    listRoles(getAuthToken())
      .then(setRoles)
      .catch(() => setError("Could not load roles from the server."));
  }, []);

  return (
    <PageShell
      title="Roles & Permissions"
      subtitle="Control which roles can access, approve, or publish changes across governance modules."
    >
      <Card title="Role matrix">
        {error && <p className="text-xs text-bad mb-3">{error}</p>}
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] text-muted">
              <th className="font-medium pb-2">Role</th>
              <th className="font-medium pb-2">Description</th>
              <th className="font-medium pb-2">Permissions</th>
            </tr>
          </thead>
          <tbody>
            {roles.map((role) => (
              <tr key={role.id} className="border-t border-line align-top">
                <td className="py-2.5 font-semibold text-ink whitespace-nowrap">{role.name}</td>
                <td className="py-2.5 text-ink">{role.description}</td>
                <td className="py-2.5 text-xs text-muted">{role.permissions_summary}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </PageShell>
  );
}
