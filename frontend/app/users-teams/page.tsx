import { PageShell } from "@/components/governance/PageShell";
import { PlannedModule } from "@/components/shell/PlannedModule";

export default function UsersTeamsPage() {
  return (
    <PageShell title="Users & Teams" subtitle="Manage user accounts, team membership, and role assignments.">
      <PlannedModule phase={5} description="User directory, team grouping, and bulk role assignment." />
    </PageShell>
  );
}
