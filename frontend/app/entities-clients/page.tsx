import { PageShell } from "@/components/governance/PageShell";
import { DpiaBlocked } from "@/components/shell/DpiaBlocked";

export default function EntitiesClientsPage() {
  return (
    <PageShell title="Entities/Clients" subtitle="Manage tenant entities and client records.">
      <DpiaBlocked />
    </PageShell>
  );
}
