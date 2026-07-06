import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { EscalationTable } from "@/components/governance/EscalationTable";

export default function EscalationQueuePage() {
  return (
    <PageShell
      title="Escalation Queue"
      subtitle="Route high-risk and restricted items by SLA, jurisdiction, owner, and evidence completeness."
    >
      <Card>
        <EscalationTable />
      </Card>
    </PageShell>
  );
}
