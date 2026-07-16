import Link from "next/link";
import { Bookmark, FileCheck2, FileSpreadsheet, FileText, Layers, Scale } from "lucide-react";
import type { RecentWorkItem } from "@/types/commandCenter";

const OBJECT_ICON: Record<RecentWorkItem["objectType"], typeof FileSpreadsheet> = {
  MATTER: FileSpreadsheet,
  WORKPAPER: FileText,
  EVIDENCE_PACK: Layers,
  REPORT: FileCheck2,
  DRAFT: FileText,
  SAVED_ANSWER: Bookmark,
  REGULATORY_ANALYSIS: Scale,
};

const OBJECT_LABEL: Record<RecentWorkItem["objectType"], string> = {
  MATTER: "Matter",
  WORKPAPER: "Workpaper",
  EVIDENCE_PACK: "Evidence pack",
  REPORT: "Report",
  DRAFT: "Draft",
  SAVED_ANSWER: "Saved answer",
  REGULATORY_ANALYSIS: "Regulatory analysis",
};

const MAX_CARDS = 5;

function relativeTime(iso: string): string {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hr`;
  return `${Math.round(hours / 24)} day${Math.round(hours / 24) === 1 ? "" : "s"}`;
}

export function ContinueYourWork({ items, spansMultipleEntities }: { items: RecentWorkItem[]; spansMultipleEntities: boolean }) {
  const visible = items.slice(0, MAX_CARDS);

  return (
    <section className="rounded-2xl border border-line bg-panel shadow-[0_1px_2px_rgba(16,24,40,.04)]">
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <h2 className="font-bold text-ink">Continue your work</h2>
        <Link href="/my-workspace" className="text-xs font-semibold text-brand hover:text-brand-2">View all recent work</Link>
      </div>
      <div className="flex gap-3 overflow-x-auto p-4">
        {visible.map((item) => {
          const Icon = OBJECT_ICON[item.objectType];
          return (
            <Link
              key={item.objectId}
              href="/my-workspace"
              className="flex w-56 shrink-0 flex-col gap-2 rounded-xl border border-line p-3.5 hover:border-brand/40 hover:bg-soft"
            >
              <Icon size={18} className="text-brand" />
              <p className="line-clamp-2 text-xs font-semibold text-ink">{item.title}</p>
              <p className="text-[11px] text-muted">
                {OBJECT_LABEL[item.objectType]} · Edited {relativeTime(item.lastInteractionAt)} ago
                {spansMultipleEntities && item.entityId && ` · ${item.entityId}`}
              </p>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
