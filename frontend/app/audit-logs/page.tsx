import { PageShell } from "@/components/governance/PageShell";
import { PlannedModule } from "@/components/shell/PlannedModule";

export default function AuditLogsPage() {
  return (
    <PageShell title="Audit Logs" subtitle="Searchable, append-only log of every governed action in the platform.">
      <PlannedModule phase={4} description="Full-text audit search, filters by actor/tenant/event type, and evidence export." />
    </PageShell>
  );
}
