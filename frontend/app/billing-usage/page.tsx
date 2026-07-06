import { PageShell } from "@/components/governance/PageShell";
import { PlannedModule } from "@/components/shell/PlannedModule";

export default function BillingUsagePage() {
  return (
    <PageShell title="Billing & Usage" subtitle="Subscription, usage metering, and invoicing. Visible to Admin roles only.">
      <PlannedModule phase={5} description="Usage metering dashboard, plan management, and invoice history." />
    </PageShell>
  );
}
