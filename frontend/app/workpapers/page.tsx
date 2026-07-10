import { PageShell } from "@/components/governance/PageShell";
import { EditableModule } from "@/components/shell/EditableModule";
import { CheckCircle2, Clock3, FileText, FolderKanban } from "lucide-react";

export default function WorkpapersPage() {
  return (
    <PageShell
      title="Workpapers"
      subtitle="Structured working papers linked to evidence and review sign-off."
      showMetrics={false}
    >
      <EditableModule
        phase={2}
        description="Workpaper editor with evidence checklist, calculation tools, and approval workflow."
        icon={FolderKanban}
        panelTitle="Workpaper register"
        primaryAction="New workpaper"
        stats={[
          { label: "Open", value: 18, tone: "brand", icon: FileText },
          { label: "Review ready", value: 7, tone: "ok", icon: CheckCircle2 },
          { label: "Due soon", value: 5, tone: "warn", icon: Clock3 },
          { label: "Evidence gaps", value: 3, tone: "bad", icon: FolderKanban },
        ]}
        records={[
          { title: "Revenue recognition memo", meta: "Atlas Financial Partners / FY26 Q2", status: "Review", tone: "warn" },
          { title: "Lease accounting schedule", meta: "Meridian Health Group / IFRS 16", status: "Draft", tone: "neutral" },
          { title: "Going concern assessment", meta: "Northstar Retail / audit file", status: "Approved", tone: "ok" },
        ]}
        fields={[
          { label: "Workpaper title", value: "Revenue recognition memo" },
          { label: "Owner", value: "Finance Manager" },
          { label: "Status", value: "Under review", type: "select" },
          { label: "Reviewer notes", value: "Tie out deferred revenue movement to evidence pack EP-204 before sign-off.", type: "textarea" },
        ]}
        checklist={["Evidence attached", "Calculations reconciled", "Reviewer assigned", "Approval history complete"]}
      />
    </PageShell>
  );
}
