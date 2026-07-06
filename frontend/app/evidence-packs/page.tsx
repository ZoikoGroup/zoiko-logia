import { PageShell } from "@/components/governance/PageShell";
import { PlannedModule } from "@/components/shell/PlannedModule";

export default function EvidencePacksPage() {
  return (
    <PageShell title="Evidence Packs" subtitle="Exportable evidence packages supporting answers, workpapers, and audits.">
      <PlannedModule phase={2} description="Evidence pack builder with redaction, approval, and export manifest." />
    </PageShell>
  );
}
