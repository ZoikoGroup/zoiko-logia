"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Info, SearchX } from "lucide-react";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import { EmptyState, utcDate } from "@/components/operations/ui";
import { SuperAdminGate, usePlatformCommand } from "@/components/platform/command";
import { SECTIONS, type PlatformSection } from "@/components/platform/sections";

/** A Super Admin sidebar section (components/platform/sections): the live
 * platform data for its area, from the same command endpoint. */
export default function PlatformSectionPage() {
  const { section: slug } = useParams<{ section: string }>();
  const section = SECTIONS.find((s) => s.slug === slug);
  if (!section) {
    return (
      <main className="flex-1 p-4 lg:p-6">
        <EmptyState icon={SearchX} title="No such platform page">
          <Link href="/super-admin" className="font-semibold text-[#1F5FAE] hover:underline">Back to the Super Admin Command Center</Link>
        </EmptyState>
      </main>
    );
  }
  return <SuperAdminGate><SectionView section={section} /></SuperAdminGate>;
}

function SectionView({ section }: { section: PlatformSection }) {
  const { data, error, loading, signedOut, reload } = usePlatformCommand();
  const Icon = section.icon;

  return (
    <main className="flex-1 space-y-4 overflow-y-auto p-4 lg:p-6">
      <section className="flex flex-col gap-3 rounded-xl bg-gradient-to-r from-hero to-hero-2 px-6 py-5 text-white shadow-[0_12px_32px_rgba(13,34,64,0.18)] sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-4">
          <span className="grid h-12 w-12 shrink-0 place-items-center rounded-xl border-2 border-white/70 bg-[#123A66] text-accent"><Icon size={22} /></span>
          <div className="min-w-0">
            <h1 className="text-2xl font-extrabold tracking-tight">{section.label}</h1>
            <p className="mt-0.5 text-sm text-white/85">{section.summary}</p>
          </div>
        </div>
        <div className="flex flex-col gap-1 text-xs text-white/80 sm:items-end">
          <Link href="/super-admin" className="inline-flex items-center gap-1 font-semibold text-white hover:underline">
            <ArrowLeft size={14} /> Command Center
          </Link>
          {data && <span>Measured {utcDate(data.generatedAt)}</span>}
        </div>
      </section>
      {section.partial && (
        <p className="flex items-start gap-2 rounded-lg border border-[#1F5FAE]/25 bg-[#E3EDFB] px-4 py-3 text-sm text-[#1F5FAE]">
          <Info size={16} className="mt-0.5 shrink-0" />
          This page shows the live platform data related to {section.label}. Its own management tools are not built yet.
        </p>
      )}
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {data && <div className="grid gap-4">{section.render(data)}</div>}
    </main>
  );
}
