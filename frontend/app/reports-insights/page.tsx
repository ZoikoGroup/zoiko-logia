import { PageShell } from "@/components/governance/PageShell";
import { PlannedModule } from "@/components/shell/PlannedModule";

export default function ReportsInsightsPage() {
  return (
    <PageShell title="Reports & Insights" subtitle="Finalized reports and cross-workflow insights.">
      <PlannedModule phase={2} description="Report library with insight dashboards and distribution controls." />
    </PageShell>
  );
}
