import { PageShell } from "@/components/governance/PageShell";
import { EditableModule } from "@/components/shell/EditableModule";
import { CheckCircle2, Clock3, PackageCheck, Paperclip } from "lucide-react";

export default function EvidencePacksPage() {
  return (
    <PageShell
      title="Evidence Packs"
      subtitle="Exportable evidence packages supporting answers, workpapers, and audits."
      showMetrics={false}
    >
      <EditableModule
        phase={2}
        description="Evidence pack builder with redaction, approval, and export manifest."
        icon={Paperclip}
        panelTitle="Evidence pack library"
        primaryAction="Build pack"
        stats={[
          { label: "Packs", value: 32, tone: "brand", icon: Paperclip },
          { label: "Export ready", value: 14, tone: "ok", icon: PackageCheck },
          { label: "Awaiting approval", value: 8, tone: "warn", icon: Clock3 },
          { label: "Redaction gaps", value: 2, tone: "bad", icon: CheckCircle2 },
        ]}
        records={[
          { title: "VAT treatment evidence pack", meta: "Saved answer SA-118 / PDF manifest", status: "Ready", tone: "ok" },
          { title: "Revenue recognition support", meta: "Workpaper WP-092 / reviewer pending", status: "Review", tone: "warn" },
          { title: "Payroll compliance export", meta: "UK bundle / redaction needed", status: "Blocked", tone: "bad" },
        ]}
        fields={[
          { label: "Pack title", value: "Revenue recognition support" },
          { label: "Export format", value: "Approved", type: "select" },
          { label: "Owner", value: "Controller" },
          { label: "Manifest note", value: "Include source snapshots, reviewer comments, and audit ledger references.", type: "textarea" },
        ]}
        checklist={["Evidence mapped", "Redactions reviewed", "Manifest generated", "Export approved"]}
      />
    </PageShell>
  );
}
