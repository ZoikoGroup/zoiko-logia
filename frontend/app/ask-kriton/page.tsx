import { PageHeader } from "@/components/governance/PageHeader";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { Search } from "lucide-react";
import { ADVISOR } from "@/lib/advisor";

export default function AskKritonPage() {
  return (
    <main className="flex-1 overflow-y-auto p-4 pt-0">
      <PageHeader
        title={ADVISOR.navLabel}
        subtitle="Entry point for AI-assisted answers. Basic query interface — full workspace ships in a later phase."
      />

      <div className="space-y-6">
        <Card>
          <div className="flex items-center gap-2 rounded-xl bg-soft border border-line px-4 py-3">
            <Search size={16} className="text-muted shrink-0" />
            <input
              type="text"
              disabled
              placeholder={ADVISOR.chatPlaceholder}
              className="w-full bg-transparent text-sm text-ink placeholder:text-muted outline-none disabled:cursor-not-allowed"
            />
            <button
              disabled
              className="shrink-0 rounded-lg bg-brand text-white text-xs font-semibold px-3.5 py-2 opacity-60 cursor-not-allowed"
            >
              Ask
            </button>
          </div>
          <p className="mt-2 text-[11px] text-muted">{ADVISOR.emptyState} Query submission is not yet wired to a live model — this is the Phase 1 entry point only.</p>
        </Card>

        <Card title="Example answer">
          <p className="text-sm text-ink leading-relaxed">
            Under IFRS, a mixed supply for VAT purposes is generally apportioned between its component parts based on
            their individual liability, unless the supply is deemed a single composite supply with one predominant
            element.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Pill tone="info">Source: HMRC VAT Notice 700</Pill>
            <Pill>Authority: Tier A</Pill>
            <Pill>Jurisdiction: UK</Pill>
            <Pill>Effective: 2026-01-01</Pill>
          </div>
        </Card>
      </div>
    </main>
  );
}
