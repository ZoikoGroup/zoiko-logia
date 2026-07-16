import { AlertOctagon, AlertTriangle, CircleAlert, Info } from "lucide-react";
import type { Severity } from "@/types/commandCenter";

// Color is never the only signal — every severity pairs an icon + text label.
const SEVERITY_META: Record<Severity, { label: string; icon: typeof AlertOctagon; tone: string }> = {
  CRITICAL: { label: "Critical", icon: AlertOctagon, tone: "text-bad bg-bad/10 border-bad/30" },
  HIGH: { label: "High", icon: AlertTriangle, tone: "text-bad bg-bad/10 border-bad/30" },
  ATTENTION: { label: "Attention", icon: CircleAlert, tone: "text-warn bg-warn/10 border-warn/30" },
  INFORMATIONAL: { label: "Informational", icon: Info, tone: "text-info bg-info/10 border-info/30" },
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  const meta = SEVERITY_META[severity];
  const Icon = meta.icon;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-bold ${meta.tone}`}>
      <Icon size={11} />
      {meta.label}
    </span>
  );
}
