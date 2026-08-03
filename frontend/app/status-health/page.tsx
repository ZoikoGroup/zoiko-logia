"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  CheckCircle2,
  Clock3,
  Info,
  Loader2,
  RefreshCw,
  ServerCrash,
} from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { Pill } from "@/components/governance/Pill";
import { PANEL_CLASS, PanelHeader } from "@/components/governance/PanelHeader";
import { StatTile } from "@/components/governance/StatTile";
import { getAuthToken, getProviderHealth, type ProviderHealth } from "@/lib/api";

// Mirrors the derived `freshness` field in
// app/domains/live_sources/router.py. "unknown" is amber rather than
// neutral on purpose: a source Kriton has never successfully contacted is
// not a healthy one, and rendering it as unremarkable is how a dead
// integration goes unnoticed for weeks.
const FRESHNESS: Record<
  ProviderHealth["freshness"],
  { tone: "ok" | "warn" | "bad" | "neutral"; label: string }
> = {
  fresh: { tone: "ok", label: "Fresh" },
  stale: { tone: "bad", label: "Stale" },
  unknown: { tone: "warn", label: "Never synced" },
  unmonitored: { tone: "neutral", label: "No SLA" },
};

// Worst first. A page whose problems sit below the fold reports problems
// nobody reads.
const SEVERITY: Record<ProviderHealth["freshness"], number> = {
  stale: 0,
  unknown: 1,
  unmonitored: 2,
  fresh: 3,
};

function formatAge(seconds: number | null): string {
  if (seconds === null) return "never";
  if (seconds < 3600) return `${Math.max(Math.floor(seconds / 60), 1)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function formatSla(seconds: number | null): string {
  if (!seconds) return "not declared";
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}

export default function StatusHealthPage() {
  const [providers, setProviders] = useState<ProviderHealth[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const token = getAuthToken();
      if (!token) {
        setError("Please sign in to view source health.");
        return;
      }
      setProviders(await getProviderHealth(token));
    } catch {
      setError("Could not load source health.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const counts = {
    fresh: providers.filter((p) => p.freshness === "fresh").length,
    stale: providers.filter((p) => p.freshness === "stale").length,
    unknown: providers.filter((p) => p.freshness === "unknown").length,
  };
  const activeCount = providers.filter((p) => p.status === "ACTIVE").length;

  const sorted = [...providers].sort(
    (a, b) =>
      SEVERITY[a.freshness] - SEVERITY[b.freshness] ||
      a.provider_key.localeCompare(b.provider_key),
  );

  return (
    <PageShell
      title="Status & Health"
      subtitle="Freshness of every authoritative source Kriton is registered to use."
      showMetrics={false}
    >
      <section className={PANEL_CLASS}>
        <PanelHeader
          icon={Activity}
          tone={counts.stale > 0 ? "bad" : "brand"}
          title="Authoritative source health"
          subtitle="Last successful contact per provider, judged against each source's own publication cadence."
          action={
            <button
              type="button"
              onClick={() => void load()}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-lg border border-line bg-chip px-3 py-1.5 text-xs font-semibold text-ink transition hover:bg-soft disabled:opacity-40"
            >
              {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
              Refresh
            </button>
          }
        />

        <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile label="Registered" value={providers.length} tone="brand" icon={Activity} />
          <StatTile label="Fresh" value={counts.fresh} tone="ok" icon={CheckCircle2} />
          <StatTile label="Stale" value={counts.stale} tone="bad" icon={ServerCrash} />
          <StatTile label="Never synced" value={counts.unknown} tone="warn" icon={Clock3} />
        </div>

        {error && (
          <p className="mt-4 rounded-lg border border-bad/30 bg-bad/10 px-3 py-2 text-xs font-medium text-bad">
            {error}
          </p>
        )}

        {!error && !loading && providers.length === 0 && (
          <p className="mt-4 rounded-lg bg-soft p-3 text-xs leading-5 text-muted">
            No providers are registered yet. Run{" "}
            <code className="font-mono">python scripts/seed_live_source_provider.py</code> from{" "}
            <code className="font-mono">backend</code>.
          </p>
        )}

        {sorted.length > 0 && (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-xs">
              <thead className="text-[11px] uppercase tracking-wide text-muted">
                <tr>
                  <th className="pb-2 pr-3 font-semibold">Source</th>
                  <th className="pb-2 pr-3 font-semibold">Freshness</th>
                  <th className="pb-2 pr-3 font-semibold">Last sync</th>
                  <th className="pb-2 pr-3 font-semibold">SLA</th>
                  <th className="pb-2 pr-3 font-semibold">Scope</th>
                  <th className="pb-2 font-semibold">Authority</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((provider) => {
                  const freshness = FRESHNESS[provider.freshness];
                  return (
                    <tr key={provider.provider_key} className="border-t border-line/60">
                      <td className="py-2 pr-3">
                        <div className="font-semibold text-ink">{provider.display_name}</div>
                        <div className="font-mono text-[10px] text-muted">
                          {provider.provider_key} · {provider.integration_type}
                        </div>
                      </td>
                      <td className="py-2 pr-3">
                        <span className="inline-flex flex-wrap gap-1">
                          <Pill tone={freshness.tone}>{freshness.label}</Pill>
                          {provider.status !== "ACTIVE" && <Pill tone="bad">{provider.status}</Pill>}
                        </span>
                      </td>
                      <td className="py-2 pr-3 text-muted">{formatAge(provider.age_seconds)}</td>
                      <td className="py-2 pr-3 text-muted">{formatSla(provider.freshness_sla_seconds)}</td>
                      <td className="py-2 pr-3 text-muted">{provider.jurisdiction}</td>
                      <td className="py-2 text-muted">rank {provider.authority_rank}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <p className="mt-4 flex items-start gap-2 rounded-lg bg-soft p-3 text-[11px] leading-5 text-muted">
          <Info size={13} className="mt-0.5 shrink-0" />
          <span>
            Last-sync times are written by the scheduled jobs and by the upstream canary
            (<code className="font-mono">scripts/check_external_sources.py</code>). A source showing
            &ldquo;never synced&rdquo; has not been contacted successfully since this environment was
            provisioned. {activeCount} of {providers.length} registered providers are ACTIVE.
          </span>
        </p>
      </section>
    </PageShell>
  );
}
