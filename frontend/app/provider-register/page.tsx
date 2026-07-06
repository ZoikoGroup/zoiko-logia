import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { PROVIDERS } from "@/lib/governance-data";

const STATUS_TONE: Record<string, "ok" | "warn" | "bad"> = {
  Active: "ok",
  Conditional: "warn",
  Suspended: "bad",
};

export default function ProviderRegisterPage() {
  return (
    <PageShell
      title="Provider Register"
      subtitle="Confirm providers are active for exact data class, region, model class, retention, and use."
    >
      <Card title="Provider due-diligence status">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] text-muted">
              <th className="font-medium pb-2">Provider</th>
              <th className="font-medium pb-2">Scope</th>
              <th className="font-medium pb-2">Status</th>
              <th className="font-medium pb-2">Restriction</th>
            </tr>
          </thead>
          <tbody>
            {PROVIDERS.map(([provider, scope, status, restriction]) => (
              <tr key={provider} className="border-t border-line">
                <td className="py-2.5 font-semibold text-ink">{provider}</td>
                <td className="py-2.5 text-ink">{scope}</td>
                <td className="py-2.5"><Pill tone={STATUS_TONE[status]}>{status}</Pill></td>
                <td className="py-2.5 text-xs text-muted">{restriction}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </PageShell>
  );
}
