import { PageShell } from "@/components/governance/PageShell";
import { EditableModule } from "@/components/shell/EditableModule";
import { CheckCircle2, Clock3, Settings, ToggleLeft } from "lucide-react";

export default function TenantSettingsPage() {
  return (
    <PageShell
      title="Tenant Settings"
      subtitle="Tenant-level configuration, branding, and defaults."
      showMetrics={false}
    >
      <EditableModule
        phase={5}
        description="Tenant configuration editor covering branding, defaults, and feature flags."
        icon={Settings}
        panelTitle="Tenant controls"
        primaryAction="Add setting"
        stats={[
          { label: "Settings", value: 46, tone: "brand", icon: Settings },
          { label: "Enabled flags", value: 18, tone: "ok", icon: CheckCircle2 },
          { label: "Pending changes", value: 4, tone: "warn", icon: Clock3 },
          { label: "Overrides", value: 7, tone: "info", icon: ToggleLeft },
        ]}
        records={[
          { title: "Default jurisdiction", meta: "United Kingdom / source scope", status: "Active", tone: "ok" },
          { title: "Feature flag: source disputes", meta: "Applies to governance roles", status: "Draft", tone: "neutral" },
          { title: "Branding profile", meta: "Logo and accent colors", status: "Review", tone: "warn" },
        ]}
        fields={[
          { label: "Setting name", value: "Feature flag: source disputes" },
          { label: "Scope", value: "Under review", type: "select" },
          { label: "Owner", value: "Admin" },
          { label: "Change note", value: "Enable disputes workflow for source governance roles after rollout approval.", type: "textarea" },
        ]}
        checklist={["Owner assigned", "Impact reviewed", "Rollback value set", "Approval captured"]}
      />
    </PageShell>
  );
}
