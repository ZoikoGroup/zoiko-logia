"use client";

import { Fragment, useEffect, useState } from "react";
import Link from "next/link";
import { Loader2, RefreshCw, ShieldCheck, ShieldAlert } from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import {
  getAuthToken,
  listAuditEvents,
  verifyAuditChain,
  type AuditEvent,
  type ChainVerifyResult,
} from "@/lib/api";

const SOURCE_TONE: Record<string, "ok" | "info"> = {
  audit_ledger: "ok",
  risk_safety_ledger: "info",
};

function formatTime(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

export default function AuditLogsPage() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [chainResult, setChainResult] = useState<ChainVerifyResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [eventName, setEventName] = useState("");
  const [subjectId, setSubjectId] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError("");
    const token = getAuthToken();
    try {
      const [eventsRes, chainRes] = await Promise.all([
        listAuditEvents(token, {
          eventName: eventName || undefined,
          subjectId: subjectId || undefined,
          limit: 100,
        }),
        verifyAuditChain(token),
      ]);
      setEvents(eventsRes);
      setChainResult(chainRes);
    } catch {
      setError("Could not load the audit ledger from the server.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const eventNames = Array.from(new Set(events.map((e) => e.event_name))).sort();
  const chainHashedCount = events.filter((e) => e.source === "audit_ledger").length;

  return (
    <PageShell
      title="Audit Logs"
      subtitle="Searchable, append-only log of every governed action in the platform."
    >
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <Card className="!p-4">
          <div className="text-2xl font-extrabold text-ink">{events.length}</div>
          <div className="text-xs text-muted mt-0.5">Events (this view)</div>
        </Card>
        <Card className="!p-4">
          <div className="text-2xl font-extrabold text-ok">{chainHashedCount}</div>
          <div className="text-xs text-muted mt-0.5">Chain-hashed (audit_ledger)</div>
        </Card>
        <Card className="!p-4">
          <div className="text-2xl font-extrabold text-info">{events.length - chainHashedCount}</div>
          <div className="text-xs text-muted mt-0.5">From risk_safety ledger</div>
        </Card>
        <Card className="!p-4">
          <div className={`flex items-center gap-1.5 text-2xl font-extrabold ${chainResult?.passed ? "text-ok" : "text-bad"}`}>
            {chainResult?.passed ? <ShieldCheck size={20} /> : <ShieldAlert size={20} />}
            {chainResult ? (chainResult.passed ? "PASS" : "FAIL") : "—"}
          </div>
          <div className="text-xs text-muted mt-0.5">
            Chain verify · {chainResult?.events_checked ?? 0} events
          </div>
        </Card>
      </div>

      <Card
        title="Ledger events"
        action={
          <button
            onClick={load}
            className="flex items-center gap-1.5 rounded-lg border border-line bg-panel px-2.5 py-1.5 text-xs font-medium text-ink hover:bg-soft"
          >
            <RefreshCw size={12} /> Refresh
          </button>
        }
      >
        <div className="flex flex-wrap gap-3 mb-4">
          <select
            value={eventName}
            onChange={(e) => setEventName(e.target.value)}
            className="rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
          >
            <option value="">All event types</option>
            {eventNames.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
          <input
            value={subjectId}
            onChange={(e) => setSubjectId(e.target.value)}
            placeholder="Filter by subject / query ID"
            className="flex-1 min-w-[220px] rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
          />
          <button
            onClick={load}
            className="rounded-lg bg-brand text-white text-sm font-semibold px-4 py-2 hover:bg-brand-2"
          >
            Search
          </button>
        </div>

        {error && <p className="text-xs text-bad mb-3">{error}</p>}

        {loading ? (
          <div className="flex items-center justify-center py-12 text-muted">
            <Loader2 className="animate-spin mr-2" size={16} /> Loading ledger…
          </div>
        ) : events.length === 0 ? (
          <p className="text-sm text-muted py-8 text-center">No audit events match this search.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] text-muted">
                <th className="font-medium pb-2">Time</th>
                <th className="font-medium pb-2">Event</th>
                <th className="font-medium pb-2">Subject</th>
                <th className="font-medium pb-2">Emitting service</th>
                <th className="font-medium pb-2">Ledger</th>
                <th className="font-medium pb-2" />
              </tr>
            </thead>
            <tbody>
              {events.map((event) => {
                const isOpen = openId === event.id;
                return (
                  <Fragment key={event.id}>
                    <tr className="border-t border-line align-top">
                      <td className="py-2.5 text-xs text-muted whitespace-nowrap">{formatTime(event.event_time)}</td>
                      <td className="py-2.5 font-semibold text-ink">{event.event_name}</td>
                      <td className="py-2.5 text-xs text-ink">
                        {event.subject_type}: {event.subject_id}
                      </td>
                      <td className="py-2.5 text-xs text-muted">{event.emitting_service}</td>
                      <td className="py-2.5">
                        <Pill tone={SOURCE_TONE[event.source] ?? "neutral"}>
                          {event.source === "audit_ledger" ? "chain-hashed" : "unverified"}
                        </Pill>
                      </td>
                      <td className="py-2.5 text-right whitespace-nowrap">
                        <button
                          onClick={() => setOpenId(isOpen ? null : event.id)}
                          className="rounded-lg border border-line bg-panel px-2.5 py-1 text-xs font-medium text-ink hover:bg-soft mr-2"
                        >
                          {isOpen ? "Hide" : "Payload"}
                        </button>
                        {event.correlation_id && (
                          <Link
                            href={`/audit-replay?correlation_id=${encodeURIComponent(event.correlation_id)}`}
                            className="text-xs text-brand hover:underline whitespace-nowrap"
                          >
                            Replay
                          </Link>
                        )}
                      </td>
                    </tr>
                    {isOpen && (
                      <tr>
                        <td colSpan={6} className="pb-4">
                          <pre className="rounded-xl border border-line bg-soft p-3 text-xs text-ink overflow-x-auto">
                            {JSON.stringify(event.payload, null, 2)}
                          </pre>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>
    </PageShell>
  );
}
