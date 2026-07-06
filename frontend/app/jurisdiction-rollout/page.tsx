import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { RolloutMini } from "@/components/governance/RolloutMini";
import { Pill } from "@/components/governance/Pill";
import { LAUNCH_GATES } from "@/lib/governance-data";

const GATE_TONE: Record<string, "ok" | "warn" | "neutral"> = {
  Passed: "ok",
  Partial: "warn",
  Pending: "neutral",
};

export default function JurisdictionRolloutPage() {
  return (
    <PageShell
      title="Jurisdiction Rollout"
      subtitle="Track pack readiness across source coverage, local expert sign-off, privacy, QA, and release gates."
    >
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <RolloutMini />
        <Card title="Launch gates">
          <table className="w-full text-sm">
            <tbody>
              {LAUNCH_GATES.map(([gate, status]) => (
                <tr key={gate} className="border-t border-line first:border-t-0">
                  <td className="py-2.5 text-ink">{gate}</td>
                  <td className="py-2.5 text-right"><Pill tone={GATE_TONE[status]}>{status}</Pill></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </PageShell>
  );
}
