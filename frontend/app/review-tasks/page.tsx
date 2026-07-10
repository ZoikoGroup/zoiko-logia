import { PageShell } from "@/components/governance/PageShell";
import { EditableModule } from "@/components/shell/EditableModule";
import { AlertTriangle, CheckCircle2, ClipboardCheck, Clock3 } from "lucide-react";

export default function ReviewTasksPage() {
  return (
    <PageShell
      title="Review Tasks"
      subtitle="Tasks assigned for review across accounting workflows."
      showMetrics={false}
    >
      <EditableModule
        phase={2}
        description="Review task queue with assignment, SLA tracking, and sign-off history."
        icon={ClipboardCheck}
        panelTitle="Review queue"
        primaryAction="Assign task"
        stats={[
          { label: "Assigned", value: 24, tone: "brand", icon: ClipboardCheck },
          { label: "Completed", value: 11, tone: "ok", icon: CheckCircle2 },
          { label: "Due today", value: 6, tone: "warn", icon: Clock3 },
          { label: "Escalated", value: 2, tone: "bad", icon: AlertTriangle },
        ]}
        records={[
          { title: "Review Q2 workpaper", meta: "Meridian Health Group / due today", status: "Due", tone: "warn" },
          { title: "Approve evidence pack", meta: "Atlas Financial Partners / assigned to Audit Partner", status: "Open", tone: "neutral" },
          { title: "Resolve source dispute", meta: "UK payroll bundle / escalated", status: "Escalated", tone: "bad" },
        ]}
        fields={[
          { label: "Task name", value: "Review Q2 workpaper" },
          { label: "Assignee", value: "Audit Partner" },
          { label: "Priority", value: "Under review", type: "select" },
          { label: "Review instruction", value: "Confirm cited source versions and sign off evidence attachment coverage.", type: "textarea" },
        ]}
        checklist={["Assignee selected", "SLA set", "Source citations checked", "Decision captured"]}
      />
    </PageShell>
  );
}
