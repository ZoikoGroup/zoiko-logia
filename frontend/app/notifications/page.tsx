"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Bell, CheckCheck, Loader2, ListChecks } from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { PanelHeader, PANEL_CLASS } from "@/components/governance/PanelHeader";
import { Pill } from "@/components/governance/Pill";
import { LoadError, formatWhen } from "@/components/governance/LiveStatus";
import { NOTIFICATIONS_CHANGED } from "@/components/layout/NotificationBell";
import {
  ApiError,
  getAuthToken,
  getMySettings,
  getNotificationSummary,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type ActionItem,
  type AppNotification,
} from "@/lib/api";

const PAGE_SIZE = 30;
const SEVERITY_TONE: Record<string, "info" | "warn" | "bad"> = { info: "info", warn: "warn", bad: "bad" };

export default function NotificationsPage() {
  const router = useRouter();
  const [items, setItems] = useState<AppNotification[] | null>(null);
  const [actions, setActions] = useState<ActionItem[]>([]);
  const [kinds, setKinds] = useState<{ kind: string; label: string }[]>([]);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [kind, setKind] = useState("");
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const token = getAuthToken();
    // The list and the action counts load separately: if the counts fail
    // (e.g. the database is briefly busy) the notifications still show.
    getNotificationSummary(token).then((summary) => setActions(summary.action_items)).catch(() => undefined);
    try {
      const page = await listNotifications(token, { unreadOnly, kind: kind || undefined, limit: PAGE_SIZE });
      setItems(page);
      setHasMore(page.length === PAGE_SIZE);
      setError("");
    } catch (err) {
      const busy = err instanceof ApiError && err.status === 503;
      setError(busy
        ? "The database is busy right now. Try again in a moment."
        : "Notifications could not be loaded. Check the backend is running and try again.");
    }
  }, [unreadOnly, kind]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on filter change
    void load();
  }, [load]);

  useEffect(() => {
    getMySettings(getAuthToken()).then((s) => setKinds(s.notification_kinds)).catch(() => setKinds([]));
  }, []);

  async function loadMore() {
    const last = items?.[items.length - 1]?.created_at;
    if (!last) return;
    setLoadingMore(true);
    try {
      const page = await listNotifications(getAuthToken(), { unreadOnly, kind: kind || undefined, before: last, limit: PAGE_SIZE });
      setItems((current) => [...(current ?? []), ...page]);
      setHasMore(page.length === PAGE_SIZE);
    } catch {
      setError("More notifications could not be loaded.");
    } finally {
      setLoadingMore(false);
    }
  }

  function announce() {
    window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED));
  }

  async function open(item: AppNotification) {
    if (!item.read) {
      try { await markNotificationRead(getAuthToken(), item.id); announce(); } catch { /* still navigate */ }
    }
    router.push(item.link);
  }

  async function markOne(item: AppNotification) {
    try {
      await markNotificationRead(getAuthToken(), item.id);
      setItems((current) => current?.map((n) => (n.id === item.id ? { ...n, read: true } : n)) ?? current);
      announce();
    } catch {
      setError("Could not mark that notification as read.");
    }
  }

  async function markAll() {
    try {
      await markAllNotificationsRead(getAuthToken());
      announce();
      await load();
    } catch {
      setError("Could not mark notifications as read.");
    }
  }

  const unreadShown = items?.some((item) => !item.read) ?? false;
  const kindLabel = Object.fromEntries(kinds.map((k) => [k.kind, k.label]));

  return (
    <PageShell title="Notifications" subtitle="Updates about your work and the things waiting for you.">
      <div className="space-y-6 max-w-4xl">
        {error && <LoadError message={error} onRetry={() => void load()} />}

        {actions.length > 0 && (
          <div className={PANEL_CLASS}>
            <PanelHeader icon={ListChecks} tone="warn" title="Needs your action" subtitle="Open work for your role right now" />
            <ul className="grid gap-2 sm:grid-cols-2">
              {actions.map((item) => (
                <li key={item.key}>
                  <Link href={item.link} className="flex items-center justify-between gap-3 rounded-lg border border-line bg-soft/30 px-3 py-2.5 text-sm text-ink hover:bg-soft">
                    <span>{item.label}</span>
                    <Pill tone={SEVERITY_TONE[item.severity] ?? "info"}>Open</Pill>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className={PANEL_CLASS}>
          <PanelHeader
            icon={Bell}
            title="All notifications"
            action={
              <button
                type="button"
                onClick={markAll}
                disabled={!unreadShown}
                className="inline-flex items-center gap-1 text-xs font-semibold text-brand disabled:text-muted disabled:opacity-60"
              >
                <CheckCheck size={13} /> Mark all as read
              </button>
            }
          />
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <div className="inline-flex rounded-lg border border-line p-0.5" role="group" aria-label="Show">
              {[{ label: "All", value: false }, { label: "Unread", value: true }].map((option) => (
                <button
                  key={option.label}
                  type="button"
                  aria-pressed={unreadOnly === option.value}
                  onClick={() => setUnreadOnly(option.value)}
                  className={`rounded-md px-3 py-1 text-xs font-semibold ${unreadOnly === option.value ? "bg-brand text-white" : "text-muted hover:bg-soft"}`}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <label className="flex items-center gap-2 text-xs text-muted">
              Type
              <select
                id="notification-kind"
                value={kind}
                onChange={(e) => setKind(e.target.value)}
                className="rounded-lg border border-line bg-panel px-2 py-1 text-xs text-ink"
              >
                <option value="">All types</option>
                {kinds.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}
              </select>
            </label>
            <Link href="/settings?tab=notifications" className="ml-auto text-xs text-brand hover:underline">
              Choose what you&apos;re notified about
            </Link>
          </div>

          {items === null ? (
            <div className="flex justify-center py-10 text-muted"><Loader2 size={18} className="animate-spin" /></div>
          ) : items.length === 0 ? (
            <p className="py-10 text-center text-sm text-muted">
              {unreadOnly || kind ? "No notifications match this filter." : "No notifications yet. They appear here when something needs you or your work changes."}
            </p>
          ) : (
            <ul className="divide-y divide-line">
              {items.map((item) => (
                <li key={item.id} className="flex items-start gap-3 py-3">
                  <span className={`mt-2 h-2 w-2 shrink-0 rounded-full ${item.read ? "bg-line" : item.severity === "bad" ? "bg-bad" : item.severity === "warn" ? "bg-warn" : "bg-info"}`} aria-hidden />
                  <button type="button" onClick={() => open(item)} className="min-w-0 flex-1 text-left">
                    <span className={`block text-sm ${item.read ? "text-muted" : "font-semibold text-ink"}`}>{item.title}</span>
                    {item.body && <span className="block text-xs text-muted">{item.body}</span>}
                    <span className="mt-0.5 block text-[11px] text-muted">
                      {formatWhen(item.created_at)}{kindLabel[item.kind] ? ` · ${kindLabel[item.kind]}` : ""}
                    </span>
                  </button>
                  {!item.read && (
                    <button type="button" onClick={() => markOne(item)} className="shrink-0 text-[11px] font-semibold text-brand hover:underline">
                      Mark read
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}

          {hasMore && (
            <div className="mt-3 text-center">
              <button
                type="button"
                onClick={loadMore}
                disabled={loadingMore}
                className="rounded-lg border border-line bg-panel px-3 py-1.5 text-xs font-semibold text-ink hover:bg-soft disabled:opacity-60"
              >
                {loadingMore ? "Loading…" : "Show older"}
              </button>
            </div>
          )}
        </div>
      </div>
    </PageShell>
  );
}
