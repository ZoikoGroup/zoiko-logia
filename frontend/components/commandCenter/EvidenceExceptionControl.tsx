import Link from "next/link";
import { ChevronRight } from "lucide-react";
import type { EvidenceExceptionSummary } from "@/types/commandCenter";

// Appears only when unresolved exceptions exist — never a permanent fixture.
export function EvidenceExceptionControl({ summary }: { summary?: EvidenceExceptionSummary }) {
  if (!summary) return null;
  const total = summary.missingCount + summary.dueForReviewCount + summary.conflictingAuthorityCount;
  if (total === 0) return null;

  return (
    <Link
      href="/evidence-packs"
      className="flex items-center justify-between gap-2 rounded-2xl border border-warn/30 bg-warn/5 p-4 text-xs hover:bg-warn/10"
    >
      <div>
        <p className="font-bold text-ink">Evidence requiring action</p>
        <p className="mt-1 text-muted">
          {summary.missingCount} missing · {summary.dueForReviewCount} due for review · {summary.conflictingAuthorityCount} conflicting authority
        </p>
      </div>
      <ChevronRight size={15} className="shrink-0 text-muted" />
    </Link>
  );
}
