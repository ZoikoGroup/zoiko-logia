import { METRICS } from "@/lib/governance-data";
import { Card } from "./Card";

export function MetricsRow() {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      {METRICS.map((m) => (
        <Card key={m.label}>
          <div className="text-xs text-muted">{m.label}</div>
          <div className="mt-1 text-2xl font-extrabold text-ink tracking-tight">{m.value}</div>
          <div className="mt-1 text-xs text-muted">{m.detail}</div>
        </Card>
      ))}
    </div>
  );
}
