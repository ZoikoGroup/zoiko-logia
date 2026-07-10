"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, Loader2, ShieldAlert } from "lucide-react";
import { Pill } from "./Pill";
import { PanelHeader, PANEL_CLASS } from "./PanelHeader";
import { createTicket, getAuthToken, getExpiringSource, type ExpiringSource } from "@/lib/api";

function severityFor(daysRemaining: number): string {
  if (daysRemaining <= 7) return "P1";
  if (daysRemaining <= 30) return "P2";
  return "P3";
}

function toneFor(daysRemaining: number): "bad" | "warn" | "ok" {
  if (daysRemaining <= 7) return "bad";
  if (daysRemaining <= 30) return "warn";
  return "ok";
}

const COUNTDOWN_STYLE: Record<"bad" | "warn" | "ok", string> = {
  bad: "bg-bad/10 text-bad",
  warn: "bg-warn/10 text-warn",
  ok: "bg-ok/10 text-ok",
};

export function License() {
  const [expiring, setExpiring] = useState<ExpiringSource | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [openingTask, setOpeningTask] = useState(false);
  const [ticketId, setTicketId] = useState<string | null>(null);

  useEffect(() => {
    getExpiringSource(getAuthToken())
      .then(setExpiring)
      .catch(() => setError("Could not load license-expiry data."))
      .finally(() => setLoading(false));
  }, []);

  async function handleOpenRenewalTask() {
    if (!expiring) return;
    setOpeningTask(true);
    try {
      const ticket = await createTicket(getAuthToken(), {
        category: "License Renewal",
        severity: severityFor(expiring.days_remaining),
        source_id: expiring.source_id,
      });
      setTicketId(ticket.id);
    } catch {
      setError("Could not open a renewal task.");
    } finally {
      setOpeningTask(false);
    }
  }

  if (loading) {
    return (
      <div className={PANEL_CLASS}>
        <PanelHeader icon={ShieldAlert} title="License-expiry countdown" />
        <div className="flex items-center gap-2 text-sm text-muted py-4">
          <Loader2 size={14} className="animate-spin" /> Checking source license expiry…
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={PANEL_CLASS}>
        <PanelHeader icon={ShieldAlert} tone="bad" title="License-expiry countdown" />
        <p className="text-xs text-bad">{error}</p>
      </div>
    );
  }

  if (!expiring) {
    return (
      <div className={PANEL_CLASS}>
        <PanelHeader icon={ShieldAlert} tone="ok" title="License-expiry countdown" action={<Pill tone="ok">All clear</Pill>} />
        <p className="text-sm text-muted">No approved sources have an expiry date within range.</p>
      </div>
    );
  }

  const tone = toneFor(expiring.days_remaining);

  return (
    <div className={PANEL_CLASS}>
      <PanelHeader
        icon={ShieldAlert}
        tone={tone}
        title="License-expiry countdown"
        action={<Pill tone={tone}>{expiring.days_remaining} days</Pill>}
      />
      <div className="flex items-center gap-3">
        <div className={`h-14 w-14 shrink-0 rounded-xl border border-line ${COUNTDOWN_STYLE[tone]} flex items-center justify-center text-xl font-extrabold`}>
          {expiring.days_remaining}
        </div>
        <div className="min-w-0 font-semibold text-ink break-words">{expiring.title}</div>
      </div>
      <p className="mt-3 text-xs text-muted leading-relaxed">
        Expires {expiring.effective_to}. Display allowed; export blocked after expiry unless renewal evidence is attached.
      </p>
      {ticketId ? (
        <div className="mt-2.5 flex items-center gap-1.5 text-xs text-ok">
          <CheckCircle2 size={13} className="shrink-0" /> Renewal task opened —{" "}
          <Link href="/support-tickets" className="underline">
            view in Support Tickets
          </Link>
        </div>
      ) : (
        <button
          onClick={handleOpenRenewalTask}
          disabled={openingTask}
          className="mt-2.5 rounded-lg border border-line bg-panel px-3 py-1.5 text-xs font-medium text-ink hover:bg-soft disabled:opacity-60 transition-all duration-200"
        >
          {openingTask ? "Opening…" : "Open renewal task"}
        </button>
      )}
    </div>
  );
}
