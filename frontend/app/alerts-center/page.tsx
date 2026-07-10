import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { ALERTS } from "@/lib/governance-data";

const SEVERITY_TONE: Record<string, "bad" | "warn"> = {
  critical: "bad",
  high: "warn",
  medium: "warn",
};

export default function AlertsCenterPage() {
  return (
    <PageShell
      title="Alerts Center"
      subtitle="Real-time operational alerts requiring attention, ranked by severity."
      showMetrics={false}
    >
      <Card title="Active alerts">
        <div className="divide-y divide-line">
          {ALERTS.map((alert) => (
            <div key={alert.title} className="flex items-start justify-between gap-4 py-3 first:pt-0 last:pb-0">
              <div>
                <div className="flex items-center gap-2">
                  <Pill tone={SEVERITY_TONE[alert.severity]}>{alert.severity}</Pill>
                  <span className="text-sm font-semibold text-ink">{alert.title}</span>
                </div>
                <p className="mt-1 text-xs text-muted">{alert.detail}</p>
              </div>
              <span className="text-[11px] text-muted whitespace-nowrap">{alert.age}</span>
            </div>
          ))}
        </div>
      </Card>
    </PageShell>
  );
}
