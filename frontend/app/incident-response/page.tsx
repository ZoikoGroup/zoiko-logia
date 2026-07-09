"use client";

import { useEffect, useState } from "react";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import {
  SecurityIncident,
  IncidentStats,
  getIncidents,
  getIncidentStats,
  updateIncident,
  closeIncident,
} from "@/lib/incident-api";

const SEVERITY_TONE: Record<string, "bad" | "warn" | "neutral"> = {
  Critical: "bad",
  High: "warn",
  Medium: "neutral",
};

const STATUS_TONE: Record<string, "warn" | "ok" | "bad"> = {
  OPEN: "bad",
  CONTAINED: "warn",
  RESOLVED: "ok",
};

export default function IncidentResponsePage() {
  const [incidents, setIncidents] = useState<SecurityIncident[]>([]);
  const [stats, setStats] = useState<IncidentStats | null>(null);
  const [selectedIncident, setSelectedIncident] = useState<SecurityIncident | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [actionNote, setActionNote] = useState("");

  const refreshData = async () => {
    try {
      const [resIncidents, resStats] = await Promise.all([
        getIncidents(),
        getIncidentStats(),
      ]);
      setIncidents(resIncidents);
      setStats(resStats);
    } catch (err) {
      setError("Could not load incidents from the server.");
    }
  };

  useEffect(() => {
    refreshData();
  }, []);

  const handleAction = async (action: string) => {
    if (!selectedIncident) return;
    setLoading(true);
    try {
      if (action === "CLOSE") {
        await closeIncident(selectedIncident.id, "Security Admin", actionNote || "Incident resolved via dashboard.");
      } else {
        await updateIncident(selectedIncident.id, action, "Security Admin", actionNote || `Action ${action} triggered.`);
      }
      setSelectedIncident(null);
      setActionNote("");
      await refreshData();
    } catch (err) {
      alert("Failed to perform action");
    } finally {
      setLoading(false);
    }
  };

  return (
    <PageShell
      title="Incident Response"
      subtitle="Track incident status from detection through resolution, with full audit linkage (ZL-T0-04)."
    >
      <div className="grid grid-cols-4 gap-4 mb-6">
        <Card title="Open Incidents">
          <div className="text-3xl font-medium mt-2">{stats?.open || 0}</div>
        </Card>
        <Card title="Contained">
          <div className="text-3xl font-medium mt-2 text-warn">{stats?.contained || 0}</div>
        </Card>
        <Card title="Critical / High">
          <div className="text-3xl font-medium mt-2 text-bad">
            {stats?.critical || 0} / {stats?.high || 0}
          </div>
        </Card>
        <Card title="Resolved (30d)">
          <div className="text-3xl font-medium mt-2 text-ok">{stats?.resolved || 0}</div>
        </Card>
      </div>

      <div className="flex gap-6">
        <div className="flex-1">
          <Card title="Security Incidents">
            {error && <p className="text-xs text-bad mb-3">{error}</p>}
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] text-muted border-b border-line">
                  <th className="font-medium pb-2">Incident ID</th>
                  <th className="font-medium pb-2">Title</th>
                  <th className="font-medium pb-2">Severity</th>
                  <th className="font-medium pb-2">Status</th>
                  <th className="font-medium pb-2">Opened</th>
                </tr>
              </thead>
              <tbody>
                {incidents.map((incident) => (
                  <tr
                    key={incident.id}
                    className={`border-b border-line cursor-pointer hover:bg-neutral-50 ${selectedIncident?.id === incident.id ? "bg-neutral-50" : ""}`}
                    onClick={() => setSelectedIncident(incident)}
                  >
                    <td className="py-3 text-xs font-mono text-muted">{incident.id}</td>
                    <td className="py-3 text-ink font-medium">{incident.title}</td>
                    <td className="py-3">
                      <Pill tone={SEVERITY_TONE[incident.severity] ?? "warn"}>{incident.severity}</Pill>
                    </td>
                    <td className="py-3">
                      <Pill tone={STATUS_TONE[incident.containment_status] ?? "warn"}>{incident.containment_status}</Pill>
                    </td>
                    <td className="py-3 text-xs text-muted whitespace-nowrap">
                      {new Date(incident.opened_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
                {incidents.length === 0 && (
                  <tr>
                    <td colSpan={5} className="py-8 text-center text-muted text-sm">
                      No incidents found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </Card>
        </div>

        {selectedIncident && (
          <div className="w-[380px]">
            <Card title="Incident Details">
              <div className="space-y-4 text-sm mt-2">
                <div>
                  <div className="text-[11px] text-muted font-medium mb-1 uppercase tracking-wide">Incident</div>
                  <div className="font-medium">{selectedIncident.title}</div>
                  <div className="text-xs font-mono text-muted mt-1">{selectedIncident.id}</div>
                </div>

                <div className="grid grid-cols-2 gap-4 border-y border-line py-4">
                  <div>
                    <div className="text-[11px] text-muted font-medium mb-1 uppercase tracking-wide">Severity</div>
                    <Pill tone={SEVERITY_TONE[selectedIncident.severity]}>{selectedIncident.severity}</Pill>
                  </div>
                  <div>
                    <div className="text-[11px] text-muted font-medium mb-1 uppercase tracking-wide">Status</div>
                    <Pill tone={STATUS_TONE[selectedIncident.containment_status]}>{selectedIncident.containment_status}</Pill>
                  </div>
                  <div>
                    <div className="text-[11px] text-muted font-medium mb-1 uppercase tracking-wide">Source</div>
                    <div className="font-mono text-xs break-all">{selectedIncident.source}</div>
                  </div>
                  <div>
                    <div className="text-[11px] text-muted font-medium mb-1 uppercase tracking-wide">Query ID</div>
                    <div className="font-mono text-xs">{selectedIncident.query_id || "N/A"}</div>
                  </div>
                </div>

                <div>
                  <div className="text-[11px] text-muted font-medium mb-3 uppercase tracking-wide">Timeline & Audit Trail</div>
                  <div className="space-y-3 relative before:absolute before:inset-0 before:ml-2 before:-translate-x-px md:before:mx-auto md:before:translate-x-0 before:h-full before:w-0.5 before:bg-gradient-to-b before:from-transparent before:via-line before:to-transparent">
                    {selectedIncident.timeline.map((entry, idx) => (
                      <div key={idx} className="relative flex items-start pl-6">
                        <div className="absolute left-0 top-1.5 w-4 h-4 rounded-full bg-surface border-2 border-primary z-10"></div>
                        <div>
                          <div className="text-xs font-medium">{entry.action.toUpperCase()} <span className="text-muted font-normal">by {entry.actor}</span></div>
                          <div className="text-xs text-muted mt-0.5">{new Date(entry.timestamp).toLocaleString()}</div>
                          <div className="text-xs mt-1 text-ink bg-neutral-50 p-2 rounded border border-line">{entry.note}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {selectedIncident.containment_status !== "RESOLVED" && (
                  <div className="pt-4 border-t border-line">
                    <div className="text-[11px] text-muted font-medium mb-2 uppercase tracking-wide">Actions</div>
                    <textarea
                      placeholder="Add investigation or resolution note..."
                      className="w-full text-xs p-2 border border-line rounded focus:outline-none focus:border-primary mb-3 min-h-[60px]"
                      value={actionNote}
                      onChange={(e) => setActionNote(e.target.value)}
                    />
                    <div className="flex gap-2">
                      {selectedIncident.containment_status === "OPEN" && (
                        <button
                          onClick={() => handleAction("CONTAIN")}
                          disabled={loading}
                          className="flex-1 bg-yellow-100 text-yellow-800 border border-yellow-200 py-1.5 rounded text-xs font-medium hover:bg-yellow-200"
                        >
                          Mark Contained
                        </button>
                      )}
                      <button
                        onClick={() => handleAction("CLOSE")}
                        disabled={loading}
                        className="flex-1 bg-green-100 text-green-800 border border-green-200 py-1.5 rounded text-xs font-medium hover:bg-green-200"
                      >
                        Resolve Incident
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </Card>
          </div>
        )}
      </div>
    </PageShell>
  );
}
