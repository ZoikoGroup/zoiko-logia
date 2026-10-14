import { PageShell } from "@/components/governance/PageShell";
import { DpiaBlocked } from "@/components/shell/DpiaBlocked";

/** Deliberately empty: client and entity data cannot be stored until the
 * Data Protection Impact Assessment and Legal/Compliance sign-off are done,
 * so this page shows the hold instead of sample records. Client engagements
 * that already exist are managed through engagements (Command Center). */
export default function EntitiesClientsPage() {
  return (
    <PageShell
      title="Entities/Clients"
      subtitle="Manage tenant entities and client records."
      showMetrics={false}
    >
      <DpiaBlocked />
    </PageShell>
  );
}
