import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { INCIDENTS } from "@/lib/governance-data";

const SEVERITY_TONE: Record<string, "bad" | "warn"> = {
  Critical: "bad",
  High: "warn",
  Medium: "warn",
};

const STATUS_TONE: Record<string, "warn" | "ok"> = {
  Investigating: "warn",
  Resolved: "ok",
};

export default function IncidentResponsePage() {
  return (
    <PageShell
      title="Incident Response"
      subtitle="Track incident status from detection through resolution, with full audit linkage."
    >
      <Card title="Incident log">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] text-muted">
              <th className="font-medium pb-2">ID</th>
              <th className="font-medium pb-2">Title</th>
              <th className="font-medium pb-2">Severity</th>
              <th className="font-medium pb-2">Status</th>
              <th className="font-medium pb-2">Opened</th>
            </tr>
          </thead>
          <tbody>
            {INCIDENTS.map(([id, title, severity, status, opened]) => (
              <tr key={id} className="border-t border-line">
                <td className="py-2.5 font-semibold text-ink whitespace-nowrap">{id}</td>
                <td className="py-2.5 text-ink">{title}</td>
                <td className="py-2.5"><Pill tone={SEVERITY_TONE[severity]}>{severity}</Pill></td>
                <td className="py-2.5"><Pill tone={STATUS_TONE[status]}>{status}</Pill></td>
                <td className="py-2.5 text-xs text-muted whitespace-nowrap">{opened}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </PageShell>
  );
}
