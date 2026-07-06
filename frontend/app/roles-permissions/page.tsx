import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { ROLES } from "@/lib/governance-data";

export default function RolesPermissionsPage() {
  return (
    <PageShell
      title="Roles & Permissions"
      subtitle="Control which roles can access, approve, or publish changes across governance modules."
    >
      <Card title="Role matrix">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] text-muted">
              <th className="font-medium pb-2">Role</th>
              <th className="font-medium pb-2">Description</th>
              <th className="font-medium pb-2">Permissions</th>
            </tr>
          </thead>
          <tbody>
            {ROLES.map(([role, description, permissions]) => (
              <tr key={role} className="border-t border-line align-top">
                <td className="py-2.5 font-semibold text-ink whitespace-nowrap">{role}</td>
                <td className="py-2.5 text-ink">{description}</td>
                <td className="py-2.5 text-xs text-muted">{permissions}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </PageShell>
  );
}
