import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { EscalationTable } from "@/components/governance/EscalationTable";
import { License } from "@/components/governance/License";
import { RolloutMini } from "@/components/governance/RolloutMini";

export default function GovernanceDashboardPage() {
  return (
    <PageShell
      title="Governance Dashboard"
      subtitle="Cross-module readiness, active approvals, drift alerts, and production blockers."
    >
      <div className="grid grid-cols-1 xl:grid-cols-[1.35fr_.9fr] gap-6">
        <Card title="Escalation queue preview" action={<span className="text-xs text-muted">Click a row to expand</span>}>
          <EscalationTable />
        </Card>
        <div className="space-y-6">
          <License />
          <RolloutMini />
        </div>
      </div>
    </PageShell>
  );
}
