import type { Deadline, EvidenceExceptionSummary, ReviewQueueItem } from "@/types/commandCenter";
import { UpcomingDeadlines } from "./UpcomingDeadlines";
import { ReviewQueue } from "./ReviewQueue";
import { EvidenceExceptionControl } from "./EvidenceExceptionControl";

export function RightRail({
  deadlines,
  deadlinesPartialFailureReason,
  reviewQueue,
  evidenceExceptionSummary,
}: {
  deadlines: Deadline[];
  deadlinesPartialFailureReason?: string;
  reviewQueue: ReviewQueueItem[];
  evidenceExceptionSummary?: EvidenceExceptionSummary;
}) {
  return (
    <div className="space-y-4">
      <UpcomingDeadlines deadlines={deadlines} partialFailureReason={deadlinesPartialFailureReason} />
      <ReviewQueue items={reviewQueue} />
      <EvidenceExceptionControl summary={evidenceExceptionSummary} />
    </div>
  );
}
