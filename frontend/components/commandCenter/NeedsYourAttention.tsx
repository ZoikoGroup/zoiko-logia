import Link from "next/link";
import type { AttentionItem } from "@/types/commandCenter";
import { SeverityBadge } from "./shared/SeverityBadge";

// §7 — hard priority order. Recency must never override this ordering.
const CATEGORY_RANK: Record<string, number> = {
  boundary_breach: 0,
  overdue_review: 1,
  material_matter: 2,
  deadline: 3,
  evidence: 4,
  standards_change: 5,
  followup: 6,
  informational: 7,
};

const MAX_ITEMS = 4;

export function NeedsYourAttention({ items, entityBound }: { items: AttentionItem[]; entityBound: boolean }) {
  const sorted = [...items].sort((a, b) => (CATEGORY_RANK[a.category] ?? 99) - (CATEGORY_RANK[b.category] ?? 99));
  const visible = sorted.slice(0, MAX_ITEMS);

  return (
    <section className="rounded-2xl border border-line bg-panel shadow-[0_1px_2px_rgba(16,24,40,.04)]">
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <h2 className="font-bold text-ink">Needs your attention</h2>
        {sorted.length > MAX_ITEMS && (
          <Link href="/escalation-queue" className="text-xs font-semibold text-brand hover:text-brand-2">View all</Link>
        )}
      </div>

      {visible.length === 0 ? (
        <div className="p-6 text-center">
          <p className="text-sm font-semibold text-ink">You are clear for now</p>
          <p className="mt-1 text-xs text-muted">No assigned matters currently require action.</p>
        </div>
      ) : (
        <ul className="divide-y divide-line">
          {visible.map((item) => (
            <li key={item.id} className="flex flex-wrap items-start justify-between gap-3 p-4">
              <div className="flex min-w-0 items-start gap-2.5">
                <SeverityBadge severity={item.severity} />
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-ink">{item.title}</p>
                  {!entityBound && <p className="mt-0.5 text-xs text-muted">{item.secondaryText}</p>}
                  {item.dueAt && (
                    <p className="mt-0.5 text-[11px] text-muted">Due {new Date(item.dueAt).toLocaleDateString()}</p>
                  )}
                </div>
              </div>
              <Link href={item.actionTarget} className="shrink-0 whitespace-nowrap text-xs font-semibold text-brand hover:text-brand-2">
                Open review →
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
