import { PageShell } from "@/components/governance/PageShell";
import { EditableModule } from "@/components/shell/EditableModule";
import { Activity, CheckCircle2, Clock3, CreditCard } from "lucide-react";

export default function BillingUsagePage() {
  return (
    <PageShell
      title="Billing & Usage"
      subtitle="Subscription, usage metering, and invoicing. Visible to Admin roles only."
      showMetrics={false}
    >
      <EditableModule
        phase={5}
        description="Usage metering dashboard, plan management, and invoice history."
        icon={CreditCard}
        panelTitle="Billing controls"
        primaryAction="Add invoice"
        stats={[
          { label: "Plan", value: "Pro", tone: "brand", icon: CreditCard },
          { label: "Paid", value: 12, tone: "ok", icon: CheckCircle2 },
          { label: "Due", value: 1, tone: "warn", icon: Clock3 },
          { label: "Usage", value: "82%", tone: "info", icon: Activity },
        ]}
        records={[
          { title: "July platform invoice", meta: "Zoiko Group / due July 31", status: "Due", tone: "warn" },
          { title: "Kriton token usage", meta: "82% of monthly allowance", status: "Active", tone: "ok" },
          { title: "Evidence export add-on", meta: "Renewal pending approval", status: "Review", tone: "warn" },
        ]}
        fields={[
          { label: "Billing item", value: "July platform invoice" },
          { label: "Status", value: "Under review", type: "select" },
          { label: "Owner", value: "Admin" },
          { label: "Invoice note", value: "Confirm evidence export add-on renewal before monthly close.", type: "textarea" },
        ]}
        checklist={["Usage reconciled", "Approver selected", "Invoice reviewed", "Renewal captured"]}
      />
    </PageShell>
  );
}
