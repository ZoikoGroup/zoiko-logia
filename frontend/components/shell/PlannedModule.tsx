import { Construction } from "lucide-react";
import { PHASE_LABELS } from "@/lib/phases";
import { Card } from "@/components/governance/Card";

export function PlannedModule({
  phase, description,
}: {
  phase: number;
  description: string;
}) {
  return (
    <Card>
      <div className="flex items-start gap-3">
        <div className="h-9 w-9 rounded-lg bg-soft border border-line flex items-center justify-center text-muted shrink-0">
          <Construction size={16} />
        </div>
        <div>
          <div className="text-sm font-semibold text-ink">
            Planned for Phase {phase}: {PHASE_LABELS[phase]}
          </div>
          <p className="mt-1 text-sm text-muted">{description}</p>
        </div>
      </div>
    </Card>
  );
}
