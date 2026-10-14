"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { InfoCard } from "@/components/governance/InfoCard";
import { Pill } from "@/components/governance/Pill";
import { LOCALIZATION_CARD } from "@/lib/governance-data";
import { ApiError, getAuthToken, getReleaseReadiness, type GateState, type ReleaseGate } from "@/lib/api";

const GATE_PILL: Record<GateState, { label: string; tone: "ok" | "bad" | "warn" | "neutral" }> = {
  passed: { label: "Passed", tone: "ok" },
  blocked: { label: "Blocked", tone: "bad" },
  partial: { label: "Partial", tone: "warn" },
  not_assessed: { label: "Not assessed", tone: "neutral" },
};

/** Release gates measured from live evidence (the same assessment as the
 * Governance Dashboard): evaluation result packs, the audit ledger, open
 * incidents, risk-policy approval, licences and escalation SLAs. A gate the
 * platform cannot check yet says so instead of claiming "Passed". */
export default function ReleaseGatesPage() {
  const [gates, setGates] = useState<ReleaseGate[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    getReleaseReadiness(getAuthToken(), controller.signal)
      .then(setGates)
      .catch((err) => {
        if (controller.signal.aborted) return;
        setError(
          err instanceof ApiError && err.status === 403
            ? "Release gates aren't available for your role."
            : "Could not load the release gates. Please try again.",
        );
      });
    return () => controller.abort();
  }, []);

  const blocked = gates?.filter((g) => g.state === "blocked") ?? [];
  const unassessed = gates?.filter((g) => g.state === "not_assessed") ?? [];

  return (
    <PageShell
      title="Release Gates"
      subtitle="No publish, deploy, launch, or export without rights, approval, risk state, audit event, and rollback point."
      showMetrics={false}
    >
      {error && (
        <p role="alert" className="mb-4 rounded-lg border border-bad/25 bg-bad/10 px-3 py-2 text-sm text-bad">
          {error}
        </p>
      )}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <Card title="Release gate checklist">
          {gates === null && !error && <p className="text-sm text-muted">Checking gates…</p>}
          {gates && (
            <>
              <p className={`mb-3 text-sm font-semibold ${blocked.length ? "text-bad" : "text-ok"}`}>
                {blocked.length
                  ? `Release blocked by ${blocked.length} gate${blocked.length === 1 ? "" : "s"}.`
                  : "No measured gate is blocking release."}
                {unassessed.length > 0 && (
                  <span className="font-normal text-muted"> {unassessed.length} not assessed yet.</span>
                )}
              </p>
              <table className="w-full text-sm">
                <tbody>
                  {gates.map((gate) => (
                    <tr key={gate.gate} className="border-t border-line first:border-t-0 align-top">
                      <td className="py-2.5 pr-3">
                        <p className="text-ink">{gate.gate}</p>
                        <p className="mt-0.5 text-xs text-muted">{gate.reason}</p>
                      </td>
                      <td className="py-2.5 text-right">
                        <Pill tone={GATE_PILL[gate.state].tone}>{GATE_PILL[gate.state].label}</Pill>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-3 text-xs text-muted">
                Evaluation runs and result packs live in{" "}
                <Link href="/evaluation-gates" className="text-brand hover:underline">Evaluation Gates</Link>; the
                full picture is on the{" "}
                <Link href="/overview/governance" className="text-brand hover:underline">Governance Dashboard</Link>.
              </p>
            </>
          )}
        </Card>
        <InfoCard heading={LOCALIZATION_CARD.heading} body={LOCALIZATION_CARD.body} />
      </div>
    </PageShell>
  );
}
