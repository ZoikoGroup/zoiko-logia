import { Card } from "@/components/governance/Card";
import { ESCALATIONS } from "@/lib/governance-data";
import type { RoleCode } from "@/lib/roles";

export const allowedRoles: RoleCode[] = ["AI Governance Lead", "Admin"];

export function GovernanceSnapshotModule() {
  return (
    <Card title="Governance Snapshot">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="text-2xl font-extrabold text-ink">{ESCALATIONS.length}</div>
          <div className="text-xs text-muted">Open escalations</div>
        </div>
        <div>
          <div className="text-2xl font-extrabold text-ink">9</div>
          <div className="text-xs text-muted">Source-drift alerts</div>
        </div>
      </div>
    </Card>
  );
}
