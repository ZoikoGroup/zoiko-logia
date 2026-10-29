"use client";

import { AlertTriangle, BadgeCheck } from "lucide-react";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import { utcDate } from "@/components/operations/ui";
import {
  Assurance, CommandMark, CommercialAssurance, DecisionQueue, EvidenceAudit, KritonControlPlane, PrivilegedAccess, Reliability,
  SummaryTiles, SuperAdminGate, TenantGovernance, usePlatformCommand,
} from "@/components/platform/command";

/** Super Admin Command Center, laid out after the ZoikoLogia command-center
 * design. Every figure is live platform metadata (components/platform/command). */
export default function SuperAdminPage() {
  return <SuperAdminGate><CommandCenter /></SuperAdminGate>;
}

function CommandCenter() {
  const { data, error, loading, signedOut, reload } = usePlatformCommand();

  return (
    <main className="flex-1 space-y-4 overflow-y-auto p-4 lg:p-6">
      <section className="relative overflow-hidden rounded-xl bg-gradient-to-r from-hero to-hero-2 px-6 py-6 text-white shadow-[0_12px_32px_rgba(13,34,64,0.18)]">
        <div className="relative flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-4">
            <CommandMark />
            <div className="min-w-0">
              <h1 className="text-2xl font-extrabold tracking-tight sm:text-[28px]">Super Admin Command Center</h1>
              <p className="mt-1 text-sm text-white/85">Platform assurance, executive decisions, and governed Kriton operations.</p>
            </div>
          </div>
          <div className="flex flex-col gap-2 text-xs text-white/85 lg:items-end lg:text-right">
            {data && (data.summary.controlExceptions > 0 ? (
              <span className="inline-flex items-center gap-2 rounded-full border border-accent px-4 py-2 text-sm font-bold text-accent">
                <AlertTriangle size={16} /> Attention required · {data.summary.controlExceptions} control exception{data.summary.controlExceptions === 1 ? "" : "s"}
              </span>
            ) : (
              <span className="inline-flex items-center gap-2 rounded-full border border-white/40 px-4 py-2 text-sm font-bold text-white">
                <BadgeCheck size={16} /> No control exceptions
              </span>
            ))}
            {data && <span>{data.tenants.total} tenants · {data.tenants.users} accounts · {data.health.measured} services monitored</span>}
            {data && <span className="uppercase tracking-wide text-white/70">Measured {utcDate(data.generatedAt)} · live platform metadata</span>}
          </div>
        </div>
      </section>
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
      {data && (
        <>
          <SummaryTiles data={data} />
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)]">
            <DecisionQueue data={data} />
            <Assurance data={data} />
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <Reliability data={data} />
            <KritonControlPlane data={data} />
            <TenantGovernance data={data} />
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <CommercialAssurance data={data} />
            <PrivilegedAccess data={data} />
            <EvidenceAudit data={data} />
          </div>
          <footer className="pb-2 text-right text-xs text-muted">Measured {utcDate(data.generatedAt)}</footer>
        </>
      )}
    </main>
  );
}
