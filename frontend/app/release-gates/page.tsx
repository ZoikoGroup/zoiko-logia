import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { InfoCard } from "@/components/governance/InfoCard";
import { Pill } from "@/components/governance/Pill";
import { RELEASE_GATES, LOCALIZATION_CARD } from "@/lib/governance-data";

const GATE_TONE: Record<string, "ok" | "warn" | "neutral"> = {
  Passed: "ok",
  Partial: "warn",
  Pending: "neutral",
};

export default function ReleaseGatesPage() {
  return (
    <PageShell
      title="Release Gates"
      subtitle="No publish, deploy, launch, or export without rights, approval, risk state, audit event, and rollback point."
      showMetrics={false}
    >
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <Card title="Release gate checklist">
          <table className="w-full text-sm">
            <tbody>
              {RELEASE_GATES.map(([gate, status]) => (
                <tr key={gate} className="border-t border-line first:border-t-0">
                  <td className="py-2.5 text-ink">{gate}</td>
                  <td className="py-2.5 text-right"><Pill tone={GATE_TONE[status]}>{status}</Pill></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <InfoCard heading={LOCALIZATION_CARD.heading} body={LOCALIZATION_CARD.body} />
      </div>
    </PageShell>
  );
}
