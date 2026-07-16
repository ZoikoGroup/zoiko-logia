import type { Severity } from "@/types/governance";

// §23.2 — all-caps short label only, color + label together (never color alone).
const SEVERITY_TONE: Record<Severity, string> = {
  CRITICAL: "text-bad bg-bad/10 border-bad/30",
  HIGH: "text-warn bg-warn/10 border-warn/30",
  MEDIUM: "text-info bg-info/10 border-info/30",
  LOW: "text-muted bg-soft border-line",
  INFORMATIONAL: "text-muted bg-soft border-line",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-bold tracking-wide ${SEVERITY_TONE[severity]}`}>
      {severity}
    </span>
  );
}
