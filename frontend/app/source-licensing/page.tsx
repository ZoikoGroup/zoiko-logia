import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { License } from "@/components/governance/License";
import { Pill } from "@/components/governance/Pill";
import { SOURCE_REGISTER } from "@/lib/governance-data";

const STATUS_TONE: Record<string, "ok" | "warn" | "bad"> = {
  Approved: "ok",
  "Pending SME": "warn",
  "Drift alert": "bad",
};

export default function SourceLicensingPage() {
  return (
    <PageShell
      title="Source Licensing"
      subtitle="Approve, hold, expire, or restrict authoritative sources before they enter RAG/source bundles."
    >
      <div className="grid grid-cols-1 xl:grid-cols-[1.35fr_.9fr] gap-6">
        <Card title="Source approval register">
          <table className="w-full text-sm">
            <tbody>
              {SOURCE_REGISTER.map(([source, status, note]) => (
                <tr key={source} className="border-t border-line first:border-t-0">
                  <td className="py-2.5 font-semibold text-ink">{source}</td>
                  <td className="py-2.5"><Pill tone={STATUS_TONE[status]}>{status}</Pill></td>
                  <td className="py-2.5 text-xs text-muted">{note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <License />
      </div>
    </PageShell>
  );
}
