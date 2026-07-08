"use client";

import { useEffect, useState } from "react";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { getAuthToken, Incident, listIncidents } from "@/lib/api";

const SEVERITY_TONE: Record<string, "bad" | "warn"> = {
  Critical: "bad",
  High: "warn",
  Medium: "warn",
};

const STATUS_TONE: Record<string, "warn" | "ok"> = {
  Investigating: "warn",
  Resolved: "ok",
};

export default function IncidentResponsePage() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    listIncidents(getAuthToken())
      .then(setIncidents)
      .catch(() => setError("Could not load incidents from the server."));
  }, []);

  return (
    <PageShell
      title="Incident Response"
      subtitle="Track incident status from detection through resolution, with full audit linkage."
    >
      <Card title="Incident log">
        {error && <p className="text-xs text-bad mb-3">{error}</p>}
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] text-muted">
              <th className="font-medium pb-2">Title</th>
              <th className="font-medium pb-2">Severity</th>
              <th className="font-medium pb-2">Status</th>
              <th className="font-medium pb-2">Opened</th>
            </tr>
          </thead>
          <tbody>
            {incidents.map((incident) => (
              <tr key={incident.id} className="border-t border-line">
                <td className="py-2.5 text-ink">{incident.title}</td>
                <td className="py-2.5">
                  <Pill tone={SEVERITY_TONE[incident.severity] ?? "warn"}>{incident.severity}</Pill>
                </td>
                <td className="py-2.5">
                  <Pill tone={STATUS_TONE[incident.status] ?? "warn"}>{incident.status}</Pill>
                </td>
                <td className="py-2.5 text-xs text-muted whitespace-nowrap">
                  {new Date(incident.opened_at).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </PageShell>
  );
}
