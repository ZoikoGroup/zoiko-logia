import { PageShell } from "@/components/governance/PageShell";
import { PlannedModule } from "@/components/shell/PlannedModule";

export default function SavedAnswersPage() {
  return (
    <PageShell title="Saved Answers" subtitle="Answers saved from Ask Kriton for reuse, citation, and review.">
      <PlannedModule phase={2} description="Saved answer library with tagging, citation export, and reuse across workpapers." />
    </PageShell>
  );
}
