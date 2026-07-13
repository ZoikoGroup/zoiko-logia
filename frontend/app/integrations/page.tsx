import { PageShell } from "@/components/governance/PageShell";
import { EditableModule } from "@/components/shell/EditableModule";
import { Activity, CheckCircle2, Clock3, Plug } from "lucide-react";

export default function IntegrationsPage() {
  return (
    <PageShell
      title="Integrations"
      subtitle="Connected systems and API integrations."
      showMetrics={false}
    >
      <EditableModule
        phase={4}
        description="Integration health, credentials management, and webhook configuration."
        icon={Plug}
        panelTitle="Connected systems"
        primaryAction="Add integration"
        stats={[
          { label: "Connected", value: 9, tone: "brand", icon: Plug },
          { label: "Healthy", value: 7, tone: "ok", icon: CheckCircle2 },
          { label: "Sync lag", value: 2, tone: "warn", icon: Clock3 },
          { label: "Events/hour", value: "1.8k", tone: "info", icon: Activity },
        ]}
        records={[
          { title: "ZoikoSuite ledger bridge", meta: "OAuth / last sync 4m ago", status: "Healthy", tone: "ok" },
          { title: "Document archive webhook", meta: "HMAC / retry policy active", status: "Review", tone: "warn" },
          { title: "Payroll source connector", meta: "Credential rotation due", status: "Due", tone: "warn" },
        ]}
        fields={[
          { label: "Integration name", value: "Document archive webhook" },
          { label: "Auth mode", value: "Approved", type: "select" },
          { label: "Owner", value: "AI Governance Lead" },
          { label: "Configuration note", value: "Rotate signing secret after webhook replay validation is complete.", type: "textarea" },
        ]}
        checklist={["Credentials stored", "Webhook verified", "Retry policy set", "Owner assigned"]}
      />
    </PageShell>
  );
}
