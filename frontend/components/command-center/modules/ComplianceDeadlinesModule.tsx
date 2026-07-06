import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { COMPLIANCE_CALENDAR } from "@/lib/governance-data";
import type { RoleCode } from "@/lib/roles";

export const allowedRoles: RoleCode[] = ["CFO", "Controller", "Tax Director", "Finance Manager", "Business Owner", "Audit Partner", "Admin"];

const STATUS_TONE: Record<string, "info" | "warn" | "bad"> = {
  Upcoming: "info",
  "At risk": "warn",
  Overdue: "bad",
};

export function ComplianceDeadlinesModule() {
  return (
    <Card title="Upcoming Compliance Deadlines">
      <div className="space-y-3">
        {COMPLIANCE_CALENDAR.slice(0, 3).map(([date, event, , status]) => (
          <div key={event} className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <div className="text-sm text-ink truncate">{event}</div>
              <div className="text-[11px] text-muted">{date}</div>
            </div>
            <Pill tone={STATUS_TONE[status]}>{status}</Pill>
          </div>
        ))}
      </div>
    </Card>
  );
}
