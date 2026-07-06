import { PageShell } from "@/components/governance/PageShell";
import { PlannedModule } from "@/components/shell/PlannedModule";

export default function WorkpapersPage() {
  return (
    <PageShell title="Workpapers" subtitle="Structured working papers linked to evidence and review sign-off.">
      <PlannedModule phase={2} description="Workpaper editor with evidence checklist, calculation tools, and approval workflow." />
    </PageShell>
  );
}
