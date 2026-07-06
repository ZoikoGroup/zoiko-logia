import { ROLLOUT } from "@/lib/governance-data";
import { Card } from "./Card";
import { Pill } from "./Pill";

const BAR_COLOR: Record<string, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  bad: "bg-bad",
};

const TEXT_COLOR: Record<string, string> = {
  ok: "text-ok",
  warn: "text-warn",
  bad: "text-bad",
};

export function RolloutMini() {
  return (
    <Card title="Jurisdiction rollout tracker" action={<Pill tone="info">Beyond competitor baseline</Pill>}>
      <div className="space-y-3">
        {ROLLOUT.map(([jurisdiction, pct, tone]) => (
          <div key={jurisdiction}>
            <div className="flex items-center justify-between text-sm">
              <span className="font-semibold text-ink">{jurisdiction}</span>
              <span className={`text-xs font-medium ${TEXT_COLOR[tone]}`}>{pct}% ready</span>
            </div>
            <div className="mt-1.5 h-2 rounded-full bg-soft border border-line overflow-hidden">
              <div className={`h-full rounded-full ${BAR_COLOR[tone]}`} style={{ width: `${pct}%` }} />
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
