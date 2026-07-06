import { PageShell } from "@/components/governance/PageShell";
import { PlannedModule } from "@/components/shell/PlannedModule";

export default function ReviewTasksPage() {
  return (
    <PageShell title="Review Tasks" subtitle="Tasks assigned for review across accounting workflows.">
      <PlannedModule phase={2} description="Review task queue with assignment, SLA tracking, and sign-off history." />
    </PageShell>
  );
}
