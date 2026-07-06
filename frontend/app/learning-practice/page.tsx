import { PageShell } from "@/components/governance/PageShell";
import { PlannedModule } from "@/components/shell/PlannedModule";

export default function LearningPracticePage() {
  return (
    <PageShell title="Learning & Practice" subtitle="Practice cases and guided learning content for skill development.">
      <PlannedModule phase={2} description="Practice case library, guided walkthroughs, and progress tracking." />
    </PageShell>
  );
}
