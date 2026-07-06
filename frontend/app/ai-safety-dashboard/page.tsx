import { PageShell } from "@/components/governance/PageShell";
import { PlannedModule } from "@/components/shell/PlannedModule";

export default function AiSafetyDashboardPage() {
  return (
    <PageShell title="AI Safety Dashboard" subtitle="Real-time view of risk classifications, refusals, and human review activity.">
      <PlannedModule phase={3} description="Safety event feed, refusal-rate trends, and human review SLA tracking." />
    </PageShell>
  );
}
