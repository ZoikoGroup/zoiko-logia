import { PageShell } from "@/components/governance/PageShell";
import { EditableModule } from "@/components/shell/EditableModule";
import { BarChart3, CheckCircle2, Clock3, FileText } from "lucide-react";

export default function ReportsInsightsPage() {
  return (
    <PageShell
      title="Reports & Insights"
      subtitle="Finalized reports and cross-workflow insights."
      showMetrics={false}
    >
      <EditableModule
        phase={2}
        description="Report library with insight dashboards and distribution controls."
        icon={BarChart3}
        panelTitle="Report library"
        primaryAction="Create report"
        stats={[
          { label: "Reports", value: 27, tone: "brand", icon: FileText },
          { label: "Published", value: 16, tone: "ok", icon: CheckCircle2 },
          { label: "In review", value: 6, tone: "warn", icon: Clock3 },
          { label: "Insights", value: 41, tone: "info", icon: BarChart3 },
        ]}
        records={[
          { title: "Q2 compliance summary", meta: "Board pack / draft distribution", status: "Draft", tone: "neutral" },
          { title: "Source governance trends", meta: "Monthly operating review", status: "Published", tone: "ok" },
          { title: "Audit readiness exceptions", meta: "Controller queue / reviewer pending", status: "Review", tone: "warn" },
        ]}
        fields={[
          { label: "Report title", value: "Q2 compliance summary" },
          { label: "Audience", value: "CFO" },
          { label: "Status", value: "Draft", type: "select" },
          { label: "Distribution note", value: "Summarize unresolved evidence gaps and upcoming compliance deadlines.", type: "textarea" },
        ]}
        checklist={["Data refreshed", "Narrative reviewed", "Recipients selected", "Approval captured"]}
      />
    </PageShell>
  );
}
