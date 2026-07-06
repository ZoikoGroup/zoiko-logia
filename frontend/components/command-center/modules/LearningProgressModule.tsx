import { Card } from "@/components/governance/Card";
import type { RoleCode } from "@/lib/roles";

export const allowedRoles: RoleCode[] = ["Learner", "Admin"];

export function LearningProgressModule() {
  return (
    <Card title="Learning Progress">
      <div className="space-y-3">
        <div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-ink">IFRS Foundations</span>
            <span className="text-xs text-muted">68%</span>
          </div>
          <div className="mt-1.5 h-2 rounded-full bg-soft border border-line overflow-hidden">
            <div className="h-full rounded-full bg-brand" style={{ width: "68%" }} />
          </div>
        </div>
        <div className="text-xs text-muted">Next practice case: Payroll termination pay (US-CA)</div>
      </div>
    </Card>
  );
}
