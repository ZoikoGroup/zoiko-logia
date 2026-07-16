import { AlertOctagon, AlertTriangle, CheckCircle2, CircleCheck, CircleHelp, Clock } from "lucide-react";
import type { DomainState } from "@/types/governance";

// §7.1/§23.1 — text + icon + color for every state. Color alone is a bug,
// so every consumer of this taxonomy should render through here.
const STATE_META: Record<DomainState, { label: string; icon: typeof CheckCircle2; tone: string }> = {
  EFFECTIVE: { label: "Effective", icon: CircleCheck, tone: "text-ok bg-ok/10 border-ok/30" },
  EFFECTIVE_WITH_OBSERVATIONS: { label: "Effective with observations", icon: CheckCircle2, tone: "text-ok bg-ok/10 border-ok/30" },
  ATTENTION_REQUIRED: { label: "Attention required", icon: AlertTriangle, tone: "text-warn bg-warn/10 border-warn/30" },
  CONTROL_FAILURE: { label: "Control failure", icon: AlertOctagon, tone: "text-bad bg-bad/10 border-bad/30" },
  ASSESSMENT_OVERDUE: { label: "Assessment overdue", icon: Clock, tone: "text-warn bg-warn/10 border-warn/30" },
  NOT_ASSESSED: { label: "Not assessed", icon: CircleHelp, tone: "text-muted bg-soft border-line" },
};

export function StateBadge({ state, size = "md" }: { state: DomainState; size?: "sm" | "md" }) {
  const meta = STATE_META[state];
  const Icon = meta.icon;
  const padding = size === "sm" ? "px-2 py-0.5 text-[10px]" : "px-2.5 py-1 text-xs";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border font-semibold ${meta.tone} ${padding}`}>
      <Icon size={size === "sm" ? 11 : 13} />
      {meta.label}
    </span>
  );
}

export { STATE_META };

// §5.3 sort order — unavailable (NOT_ASSESSED) always sorts last, never green.
export const DOMAIN_STATE_RANK: Record<DomainState, number> = {
  CONTROL_FAILURE: 0,
  ASSESSMENT_OVERDUE: 1,
  ATTENTION_REQUIRED: 2,
  EFFECTIVE_WITH_OBSERVATIONS: 3,
  EFFECTIVE: 4,
  NOT_ASSESSED: 5,
};
