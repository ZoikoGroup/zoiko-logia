import { PageShell } from "@/components/governance/PageShell";
import { EditableModule } from "@/components/shell/EditableModule";
import { Activity, CheckCircle2, Clock3, ServerCrash } from "lucide-react";

export default function StatusHealthPage() {
  return (
    <PageShell
      title="Status & Health"
      subtitle="Live system status across all ZoikoLogia services."
      showMetrics={false}
    >
      <EditableModule
        phase={4}
        description="Service uptime, latency, and incident history dashboard."
        icon={Activity}
        panelTitle="Service status"
        primaryAction="Add monitor"
        stats={[
          { label: "Services", value: 14, tone: "brand", icon: Activity },
          { label: "Operational", value: 13, tone: "ok", icon: CheckCircle2 },
          { label: "Degraded", value: 1, tone: "warn", icon: Clock3 },
          { label: "Incidents", value: 0, tone: "bad", icon: ServerCrash },
        ]}
        records={[
          { title: "Kriton orchestration API", meta: "p95 420ms / no open incident", status: "Healthy", tone: "ok" },
          { title: "Source ingestion worker", meta: "queue delay 12m / backfill active", status: "Degraded", tone: "warn" },
          { title: "Audit ledger archive", meta: "last chain check passed", status: "Healthy", tone: "ok" },
        ]}
        fields={[
          { label: "Monitor name", value: "Source ingestion worker" },
          { label: "Severity", value: "Under review", type: "select" },
          { label: "Owner", value: "Operations" },
          { label: "Runbook note", value: "Scale ingestion worker if queue delay remains above 15 minutes for two checks.", type: "textarea" },
        ]}
        checklist={["Metric source linked", "Alert rule active", "Runbook assigned", "Incident route tested"]}
      />
    </PageShell>
  );
}
