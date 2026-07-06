import { PageShell } from "@/components/governance/PageShell";
import { PlannedModule } from "@/components/shell/PlannedModule";

export default function RagSourceBundlesPage() {
  return (
    <PageShell title="RAG Source Bundles" subtitle="Source bundles assembled for retrieval-augmented answer generation.">
      <PlannedModule phase={3} description="Source bundle inspector showing retrieval candidates, exclusions, and citation mapping per answer." />
    </PageShell>
  );
}
