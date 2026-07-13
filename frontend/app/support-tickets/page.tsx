"use client";

import { FormEvent, useEffect, useState } from "react";
import { PageShell } from "@/components/governance/PageShell";
import { Pill } from "@/components/governance/Pill";
import { PanelHeader, PANEL_CLASS } from "@/components/governance/PanelHeader";
import { LifeBuoy, ListChecks } from "lucide-react";
import {
  ApiError,
  createTicket,
  getAuthToken,
  listTickets,
  Ticket,
  updateTicketStatus,
} from "@/lib/api";

const CATEGORIES = ["accuracy", "source", "risk", "access", "workflow", "privacy", "billing"];
const SEVERITIES = ["P0", "P1", "P2", "P3", "P4"];

const SEVERITY_TONE: Record<string, "bad" | "warn" | "neutral"> = {
  P0: "bad",
  P1: "bad",
  P2: "warn",
  P3: "neutral",
  P4: "neutral",
};

export default function SupportTicketsPage() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [error, setError] = useState("");
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const [category, setCategory] = useState(CATEGORIES[0]);
  const [severity, setSeverity] = useState("P3");

  function loadTickets() {
    listTickets(getAuthToken())
      .then(setTickets)
      .catch((err) => {
        setError(
          err instanceof ApiError && err.status === 403
            ? "Admin role required to view support tickets."
            : "Could not load tickets from the server."
        );
      });
  }

  useEffect(loadTickets, []);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setFormError("");
    setSubmitting(true);
    try {
      await createTicket(getAuthToken(), { category, severity });
      loadTickets();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Could not create ticket.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleClose(ticket: Ticket) {
    const next = ticket.status === "Open" ? "Closed" : "Open";
    await updateTicketStatus(getAuthToken(), ticket.id, next).catch(() => null);
    loadTickets();
  }

  return (
    <PageShell
      title="Support Tickets"
      subtitle="Ticket intake and classification — category, severity, and routing status."
      showMetrics={false}
    >
      <div className={`${PANEL_CLASS} mb-4`}>
        <PanelHeader icon={LifeBuoy} tone="warn" title="New ticket" />
        <form onSubmit={handleCreate} className="grid grid-cols-1 sm:grid-cols-3 gap-3 items-end">
          <div>
            <label className="block text-xs font-medium text-muted mb-1.5">Category</label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-muted mb-1.5">Severity</label>
            <select
              value={severity}
              onChange={(e) => setSeverity(e.target.value)}
              className="w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
            >
              {SEVERITIES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          <div>
            {formError && <p className="text-xs text-bad mb-2">{formError}</p>}
            <button
              type="submit"
              disabled={submitting}
              className="rounded-lg bg-brand text-white text-sm font-semibold px-4 py-2 hover:bg-brand-2 disabled:opacity-60"
            >
              {submitting ? "Creating..." : "Create ticket"}
            </button>
          </div>
        </form>
      </div>

      <div className={PANEL_CLASS}>
        <PanelHeader icon={ListChecks} title="Tickets" subtitle={`${tickets.length} total`} />
        {error && <p className="text-xs text-bad mb-3">{error}</p>}
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] text-muted">
              <th className="font-medium pb-2">Category</th>
              <th className="font-medium pb-2">Severity</th>
              <th className="font-medium pb-2">Status</th>
              <th className="font-medium pb-2">Created</th>
              <th className="font-medium pb-2" />
            </tr>
          </thead>
          <tbody>
            {tickets.map((ticket) => (
              <tr key={ticket.id} className="border-t border-line align-top">
                <td className="py-2.5 font-semibold text-ink whitespace-nowrap">{ticket.category}</td>
                <td className="py-2.5">
                  <Pill tone={SEVERITY_TONE[ticket.severity] ?? "neutral"}>{ticket.severity}</Pill>
                </td>
                <td className="py-2.5">
                  <Pill tone={ticket.status === "Open" ? "warn" : "ok"}>{ticket.status}</Pill>
                </td>
                <td className="py-2.5 text-xs text-muted whitespace-nowrap">
                  {new Date(ticket.created_at).toLocaleString()}
                </td>
                <td className="py-2.5 text-right">
                  <button onClick={() => handleClose(ticket)} className="text-xs text-brand hover:underline">
                    {ticket.status === "Open" ? "Close" : "Reopen"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PageShell>
  );
}
