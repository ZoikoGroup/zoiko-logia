import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { AUDIT_TIMELINE } from "@/lib/governance-data";

export default function AuditReplayPage() {
  return (
    <PageShell
      title="Audit Replay"
      subtitle="Replay query, source bundle, prompt/model version, answer version, risk decision, and admin action trail."
    >
      <Card title="Full audit log replay" action={<Pill>Query Q-1842</Pill>}>
        <div className="space-y-0">
          {AUDIT_TIMELINE.map(([time, event, description]) => (
            <div key={time} className="grid grid-cols-[110px_220px_1fr] gap-3 border-t border-line first:border-t-0 py-2.5 text-sm">
              <span className="text-xs text-muted">{time}</span>
              <span className="font-semibold text-ink">{event}</span>
              <span className="text-xs text-muted">{description}</span>
            </div>
          ))}
        </div>
      </Card>
    </PageShell>
  );
}
