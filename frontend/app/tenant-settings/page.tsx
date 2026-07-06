import { PageShell } from "@/components/governance/PageShell";
import { PlannedModule } from "@/components/shell/PlannedModule";

export default function TenantSettingsPage() {
  return (
    <PageShell title="Tenant Settings" subtitle="Tenant-level configuration, branding, and defaults.">
      <PlannedModule phase={5} description="Tenant configuration editor covering branding, defaults, and feature flags." />
    </PageShell>
  );
}
