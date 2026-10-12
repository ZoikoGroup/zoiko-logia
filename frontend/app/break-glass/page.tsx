"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { useAuth } from "@/hooks/useAuth";
import {
  ApiError,
  actOnBreakGlass,
  getAuthToken,
  listBreakGlass,
  listBreakGlassPermissions,
  requestBreakGlass,
  type BreakGlassGrant,
} from "@/lib/api";

const DURATIONS = [30, 60, 120, 240];

const STATUS_TONE: Record<BreakGlassGrant["status"], "ok" | "warn" | "bad" | "neutral" | "info"> = {
  requested: "info",
  active: "warn",
  expired: "neutral",
  revoked: "neutral",
  rejected: "bad",
};

function when(value: string | null): string {
  return value ? new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "—";
}

/** Emergency, time-boxed elevation. Anyone may ask; a different Admin must
 * approve; it ends on its own; and once ended, another Admin reviews it. */
export default function BreakGlassPage() {
  const { profile } = useAuth();
  const isAdmin = profile?.role === "Admin";
  const [grants, setGrants] = useState<BreakGlassGrant[]>([]);
  const [available, setAvailable] = useState<string[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [duration, setDuration] = useState(60);
  const [reviewing, setReviewing] = useState<string | null>(null);
  const [reviewNotes, setReviewNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const apply = useCallback((nextGrants: BreakGlassGrant[], permissions?: string[]) => {
    setGrants(nextGrants);
    if (permissions) setAvailable(permissions);
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([listBreakGlass(getAuthToken()), listBreakGlassPermissions(getAuthToken())])
      .then(([nextGrants, permissions]) => {
        if (!cancelled) apply(nextGrants, permissions);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load break-glass access.");
      });
    return () => {
      cancelled = true;
    };
  }, [apply]);

  async function run(action: () => Promise<unknown>, done: string) {
    setError("");
    setNotice("");
    setBusy(true);
    try {
      await action();
      setNotice(done);
      apply(await listBreakGlass(getAuthToken()));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  function handleRequest(e: FormEvent) {
    e.preventDefault();
    return run(async () => {
      await requestBreakGlass(getAuthToken(), { permissions: selected, reason, duration_minutes: duration });
      setSelected([]);
      setReason("");
    }, "Request sent. Another administrator must approve it before it takes effect.");
  }

  function act(grant: BreakGlassGrant, action: "approve" | "reject" | "revoke") {
    const done = { approve: "Access granted.", reject: "Request rejected.", revoke: "Access ended." }[action];
    return run(() => actOnBreakGlass(getAuthToken(), grant.id, action), done);
  }

  function submitReview(e: FormEvent, grant: BreakGlassGrant) {
    e.preventDefault();
    return run(async () => {
      await actOnBreakGlass(getAuthToken(), grant.id, "review", reviewNotes);
      setReviewing(null);
      setReviewNotes("");
    }, "Review recorded.");
  }

  const awaitingReview = grants.filter((g) => g.needs_review).length;

  return (
    <PageShell
      title="Break-glass access"
      subtitle="Time-limited emergency permissions — approved by a second administrator, reviewed afterwards, fully audited."
      showMetrics={false}
    >
      {error && (
        <p role="alert" className="mb-4 rounded-lg border border-bad/25 bg-bad/10 px-3 py-2 text-sm text-bad">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="mb-4 rounded-lg border border-ok/25 bg-ok/10 px-3 py-2 text-sm text-ink">
          {notice}
        </p>
      )}
      {isAdmin && awaitingReview > 0 && (
        <p className="mb-4 rounded-lg border border-warn/30 bg-warn/10 px-3 py-2 text-sm text-ink">
          {awaitingReview} ended grant{awaitingReview === 1 ? "" : "s"} awaiting post-use review.
        </p>
      )}

      <Card title="Request emergency access" className="mb-4">
        <form onSubmit={handleRequest} className="space-y-3">
          <fieldset>
            <legend className="mb-1.5 text-xs font-medium text-muted">Permissions needed</legend>
            <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-3">
              {available.map((permission) => (
                <label key={permission} className="flex items-center gap-2 text-sm text-ink">
                  <input
                    type="checkbox"
                    checked={selected.includes(permission)}
                    onChange={(e) =>
                      setSelected((prev) => (e.target.checked ? [...prev, permission] : prev.filter((p) => p !== permission)))
                    }
                    className="h-4 w-4 accent-brand"
                  />
                  <code className="text-xs">{permission}</code>
                </label>
              ))}
            </div>
          </fieldset>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_auto] items-end">
            <div>
              <label htmlFor="bg-reason" className="mb-1.5 block text-xs font-medium text-muted">
                Reason (incident or ticket, and what you need to do)
              </label>
              <textarea
                id="bg-reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                required
                rows={2}
                className="w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
              />
            </div>
            <div>
              <label htmlFor="bg-duration" className="mb-1.5 block text-xs font-medium text-muted">For</label>
              <select
                id="bg-duration"
                value={duration}
                onChange={(e) => setDuration(Number(e.target.value))}
                className="rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
              >
                {DURATIONS.map((m) => (
                  <option key={m} value={m}>
                    {m < 60 ? `${m} minutes` : `${m / 60} hour${m === 60 ? "" : "s"}`}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <button
            type="submit"
            disabled={busy || selected.length === 0}
            className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-2 disabled:opacity-60"
          >
            Request access
          </button>
        </form>
      </Card>

      <Card title={isAdmin ? "All requests and grants" : "Your requests and grants"}>
        {grants.length === 0 ? (
          <p className="text-sm text-muted">No break-glass requests yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] text-muted">
                  <th className="font-medium pb-2">Person</th>
                  <th className="font-medium pb-2">Permissions</th>
                  <th className="font-medium pb-2">Reason</th>
                  <th className="font-medium pb-2">Status</th>
                  <th className="font-medium pb-2">Window</th>
                  <th className="font-medium pb-2" />
                </tr>
              </thead>
              <tbody>
                {grants.map((grant) => {
                  const own = grant.user_id === profile?.id;
                  return (
                    <tr key={grant.id} className="border-t border-line align-top">
                      <td className="py-2.5 font-semibold text-ink whitespace-nowrap">{grant.user_name}</td>
                      <td className="py-2.5">
                        {grant.permissions.map((p) => (
                          <code key={p} className="mr-1 text-xs">{p}</code>
                        ))}
                      </td>
                      <td className="py-2.5 text-ink max-w-xs">{grant.reason}</td>
                      <td className="py-2.5">
                        <Pill tone={STATUS_TONE[grant.status]}>{grant.status}</Pill>
                        {grant.needs_review && <span className="ml-1 text-[11px] text-warn">review due</span>}
                      </td>
                      <td className="py-2.5 text-xs text-muted whitespace-nowrap">
                        {grant.status === "requested"
                          ? `${grant.duration_minutes} min, from approval`
                          : `${when(grant.activated_at)} → ${when(grant.ended_at ?? grant.expires_at)}`}
                      </td>
                      <td className="py-2.5 text-right whitespace-nowrap">
                        <span className="inline-flex gap-3">
                          {isAdmin && !own && grant.status === "requested" && (
                            <>
                              <button onClick={() => act(grant, "approve")} disabled={busy} className="text-xs text-brand hover:underline">
                                Approve
                              </button>
                              <button onClick={() => act(grant, "reject")} disabled={busy} className="text-xs text-bad hover:underline">
                                Reject
                              </button>
                            </>
                          )}
                          {grant.status === "active" && (own || isAdmin) && (
                            <button onClick={() => act(grant, "revoke")} disabled={busy} className="text-xs text-bad hover:underline">
                              End now
                            </button>
                          )}
                          {isAdmin && !own && grant.needs_review && reviewing !== grant.id && (
                            <button
                              onClick={() => {
                                setReviewing(grant.id);
                                setReviewNotes("");
                              }}
                              className="text-xs text-brand hover:underline"
                            >
                              Review
                            </button>
                          )}
                        </span>
                        {reviewing === grant.id && (
                          <form onSubmit={(e) => submitReview(e, grant)} className="mt-2 flex flex-col items-end gap-2">
                            <textarea
                              aria-label="Review notes"
                              value={reviewNotes}
                              onChange={(e) => setReviewNotes(e.target.value)}
                              required
                              rows={2}
                              placeholder="What was done with this access, and was it appropriate?"
                              className="w-64 rounded-lg border border-line bg-soft px-2 py-1 text-xs text-ink outline-none focus:border-brand"
                            />
                            <span className="inline-flex gap-2">
                              <button type="submit" disabled={busy} className="text-xs font-semibold text-brand hover:underline">
                                Save review
                              </button>
                              <button type="button" onClick={() => setReviewing(null)} className="text-xs text-muted hover:underline">
                                Cancel
                              </button>
                            </span>
                          </form>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </PageShell>
  );
}
