import { PageShell } from "@/components/governance/PageShell";
import { DpiaBlocked } from "@/components/shell/DpiaBlocked";
import { EditableModule } from "@/components/shell/EditableModule";
import { Building, CheckCircle2, Clock3, ShieldAlert } from "lucide-react";

export default function EntitiesClientsPage() {
  return (
    <PageShell
      title="Entities/Clients"
      subtitle="Manage tenant entities and client records."
      showMetrics={false}
    >
      <div className="space-y-4">
        <DpiaBlocked />
        <EditableModule
          phase={5}
          description="Privacy-safe intake workspace staged for DPIA approval before client/entity data models are activated."
          icon={Building}
          panelTitle="Entity intake queue"
          primaryAction="Draft intake"
          stats={[
            { label: "Drafts", value: 6, tone: "brand", icon: Building },
            { label: "DPIA ready", value: 3, tone: "ok", icon: CheckCircle2 },
            { label: "Pending legal", value: 2, tone: "warn", icon: Clock3 },
            { label: "Blocked", value: 1, tone: "bad", icon: ShieldAlert },
          ]}
          records={[
            { title: "Atlas Financial Partners", meta: "Client intake / no live data model", status: "DPIA", tone: "warn" },
            { title: "Meridian Health Group", meta: "Entity profile / legal review", status: "Review", tone: "warn" },
            { title: "Northstar Retail", meta: "Sandbox-only draft", status: "Draft", tone: "neutral" },
          ]}
          fields={[
            { label: "Display name", value: "Atlas Financial Partners" },
            { label: "Classification", value: "Under review", type: "select" },
            { label: "Owner", value: "Admin" },
            { label: "Privacy note", value: "Keep intake metadata only until DPIA and Legal/Compliance sign-off are complete.", type: "textarea" },
          ]}
          checklist={["DPIA decision linked", "Data minimization checked", "Legal owner assigned", "Retention rule drafted"]}
        />
      </div>
    </PageShell>
  );
}
