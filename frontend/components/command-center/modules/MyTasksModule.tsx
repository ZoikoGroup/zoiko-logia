import { CheckSquare } from "lucide-react";
import { Card } from "@/components/governance/Card";
import type { RoleCode } from "@/lib/roles";

export const allowedRoles: RoleCode[] = ["CFO", "Controller", "Tax Director", "Finance Manager", "Business Owner", "Audit Partner", "Admin"];

const TASKS = [
  { label: "Review Q2 workpaper — Meridian Health Group", due: "Due today" },
  { label: "Approve evidence pack — Atlas Financial Partners", due: "Due tomorrow" },
  { label: "Sign off jurisdiction rollout readiness — UK", due: "Due in 3 days" },
];

export function MyTasksModule() {
  return (
    <Card title="My Tasks">
      <div className="space-y-3">
        {TASKS.map((task) => (
          <div key={task.label} className="flex items-start gap-2.5">
            <CheckSquare size={15} className="text-brand mt-0.5 shrink-0" />
            <div>
              <div className="text-sm text-ink">{task.label}</div>
              <div className="text-[11px] text-muted">{task.due}</div>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
