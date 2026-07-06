import { PageShell } from "@/components/governance/PageShell";
import { PlannedModule } from "@/components/shell/PlannedModule";

export default function DraftsReportsPage() {
  return (
    <PageShell title="Drafts & Reports" subtitle="In-progress reports and drafts generated from Kriton answers.">
      <PlannedModule phase={2} description="Draft report editor with evidence linking and export to Reports & Insights." />
    </PageShell>
  );
}
