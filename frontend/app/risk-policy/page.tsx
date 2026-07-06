import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { RISK_RULES } from "@/lib/governance-data";

export default function RiskPolicyPage() {
  return (
    <PageShell
      title="Risk Policy"
      subtitle="Edit draft/staging risk rules with maker-checker approval, impact preview, test pack, rollback point."
    >
      <Card title="Risk policy deployment" action={<Pill tone="warn">Draft v2026.07.03</Pill>}>
        <table className="w-full text-sm">
          <tbody>
            {RISK_RULES.map(([rule, description]) => (
              <tr key={rule} className="border-t border-line first:border-t-0">
                <td className="py-2.5 font-semibold text-ink w-56 align-top">{rule}</td>
                <td className="py-2.5 text-muted align-top">{description}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="mt-4 flex flex-wrap gap-2">
          <button className="rounded-lg border border-line bg-panel px-3 py-1.5 text-xs font-medium text-ink hover:bg-soft">
            Run regression pack
          </button>
          <button className="rounded-lg border border-line bg-panel px-3 py-1.5 text-xs font-medium text-ink hover:bg-soft">
            Preview impact
          </button>
          <button className="rounded-lg border border-line bg-panel px-3 py-1.5 text-xs font-medium text-ink hover:bg-soft">
            Request approver
          </button>
        </div>
      </Card>
    </PageShell>
  );
}
