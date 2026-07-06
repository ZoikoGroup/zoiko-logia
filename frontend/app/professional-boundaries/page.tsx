import { PageShell } from "@/components/governance/PageShell";
import { PlannedModule } from "@/components/shell/PlannedModule";

export default function ProfessionalBoundariesPage() {
  return (
    <PageShell title="Professional Boundaries" subtitle="Rules governing what Kriton can and cannot answer without human review.">
      <PlannedModule phase={3} description="Professional boundary rule editor and permitted/prohibited output checklist." />
    </PageShell>
  );
}
