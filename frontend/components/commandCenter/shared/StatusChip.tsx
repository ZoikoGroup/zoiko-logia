import type { MatterStatus } from "@/types/commandCenter";

// Canonical status taxonomy — render exactly these labels, no synonyms.
const STATUS_LABEL: Record<MatterStatus, string> = {
  DRAFT: "Draft",
  IN_PROGRESS: "In progress",
  WAITING_FOR_EVIDENCE: "Waiting for evidence",
  WAITING_FOR_CLIENT: "Waiting for client",
  WAITING_FOR_REVIEWER: "Waiting for reviewer",
  HUMAN_REVIEW_REQUIRED: "Human review required",
  CHANGES_REQUESTED: "Changes requested",
  APPROVED: "Approved",
  BLOCKED: "Blocked",
  CLOSED_ARCHIVED: "Closed/Archived",
};

const STATUS_TONE: Record<MatterStatus, string> = {
  DRAFT: "text-muted bg-soft border-line",
  IN_PROGRESS: "text-info bg-info/10 border-info/30",
  WAITING_FOR_EVIDENCE: "text-warn bg-warn/10 border-warn/30",
  WAITING_FOR_CLIENT: "text-warn bg-warn/10 border-warn/30",
  WAITING_FOR_REVIEWER: "text-warn bg-warn/10 border-warn/30",
  HUMAN_REVIEW_REQUIRED: "text-bad bg-bad/10 border-bad/30",
  CHANGES_REQUESTED: "text-warn bg-warn/10 border-warn/30",
  APPROVED: "text-ok bg-ok/10 border-ok/30",
  BLOCKED: "text-bad bg-bad/10 border-bad/30",
  CLOSED_ARCHIVED: "text-muted bg-soft border-line",
};

export function StatusChip({ status }: { status: MatterStatus }) {
  return (
    <span className={`inline-flex w-fit items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${STATUS_TONE[status]}`}>
      {STATUS_LABEL[status]}
    </span>
  );
}

export { STATUS_LABEL };
