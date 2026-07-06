import { PageShell } from "@/components/governance/PageShell";
import { PlannedModule } from "@/components/shell/PlannedModule";

export default function IntegrationsPage() {
  return (
    <PageShell title="Integrations" subtitle="Connected systems and API integrations.">
      <PlannedModule phase={4} description="Integration health, credentials management, and webhook configuration." />
    </PageShell>
  );
}
