import { ShieldAlert } from "lucide-react";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";

export function DpiaBlocked() {
  return (
    <Card action={<Pill tone="warn">Engineering hold</Pill>}>
      <div className="flex items-start gap-3">
        <div className="h-9 w-9 rounded-lg bg-warn/10 text-warn flex items-center justify-center shrink-0">
          <ShieldAlert size={18} />
        </div>
        <div>
          <div className="text-sm font-semibold text-ink">Blocked pending DPIA sign-off</div>
          <p className="mt-1 text-sm text-muted">
            Engineering on this module is blocked pending Data Protection Impact Assessment and Legal/Compliance
            sign-off. No data model has been implemented for Entities/Clients.
          </p>
        </div>
      </div>
    </Card>
  );
}
