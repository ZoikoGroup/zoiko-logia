"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Bell, CheckCheck, Loader2 } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import {
  getAuthToken,
  getNotificationSummary,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type AppNotification,
  type NotificationSummary,
} from "@/lib/api";
import { formatWhen } from "@/components/governance/LiveStatus";

const POLL_MS = 60_000;
/** Fired after notifications are read elsewhere (e.g. /notifications), so the badge updates at once. */
export const NOTIFICATIONS_CHANGED = "zoiko-notifications-changed";

const SEVERITY_DOT: Record<string, string> = { info: "bg-info", warn: "bg-warn", bad: "bg-bad" };

export function NotificationBell() {
  const { session } = useAuth();
  // Keyed on the user, not the session object, so token refreshes don't
  // restart polling (each restart used to fetch immediately).
  const userId = session?.user?.id ?? "";
  const router = useRouter();
  const [summary, setSummary] = useState<NotificationSummary | null>(null);
  const [recent, setRecent] = useState<AppNotification[] | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const panelRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  const refresh = useCallback(async () => {
    if (!userId) return;
    try {
      setSummary(await getNotificationSummary(getAuthToken()));
      setError("");
    } catch {
      setError("Notifications could not be loaded.");
    }
  }, [userId]);

  const loadRecent = useCallback(async () => {
    try {
      setRecent(await listNotifications(getAuthToken(), { limit: 8 }));
    } catch {
      setRecent([]);
    }
  }, []);

  useEffect(() => {
    if (!userId) return;
    const tick = () => { if (document.visibilityState === "visible") void refresh(); };
    const first = window.setTimeout(tick, 0);
    const timer = window.setInterval(tick, POLL_MS);
    window.addEventListener("focus", tick);
    window.addEventListener(NOTIFICATIONS_CHANGED, tick);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(timer);
      window.removeEventListener("focus", tick);
      window.removeEventListener(NOTIFICATIONS_CHANGED, tick);
    };
  }, [userId, refresh]);

  useEffect(() => {
    if (!open) return;
    function onPointer(event: MouseEvent) {
      const target = event.target as Node;
      if (!panelRef.current?.contains(target) && !buttonRef.current?.contains(target)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") { setOpen(false); buttonRef.current?.focus(); }
    }
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onPointer); document.removeEventListener("keydown", onKey); };
  }, [open]);

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next) { void loadRecent(); void refresh(); }
  }

  async function openItem(item: AppNotification) {
    setOpen(false);
    if (!item.read) {
      try { await markNotificationRead(getAuthToken(), item.id); } catch { /* still navigate */ }
      void refresh();
    }
    router.push(item.link);
  }

  async function markAll() {
    try {
      await markAllNotificationsRead(getAuthToken());
      setRecent((items) => items?.map((item) => ({ ...item, read: true })) ?? items);
      void refresh();
    } catch {
      setError("Could not mark notifications as read.");
    }
  }

  const unread = summary?.unread ?? 0;
  const actions = summary?.action_items ?? [];
  const label = unread
    ? `Notifications, ${unread} unread`
    : actions.length ? `Notifications, ${actions.length} item${actions.length === 1 ? "" : "s"} need your action` : "Notifications";

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        type="button"
        onClick={toggle}
        aria-label={label}
        title={label}
        aria-expanded={open}
        aria-haspopup="dialog"
        className="relative h-10 w-10 flex items-center justify-center rounded-xl border border-line bg-panel text-muted hover:bg-soft"
      >
        <Bell size={17} />
        {unread > 0 ? (
          <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] rounded-full bg-bad px-1 text-[10px] font-bold leading-[18px] text-white text-center">
            {unread > 99 ? "99+" : unread}
          </span>
        ) : actions.length > 0 ? (
          <span className="absolute top-2 right-2 h-2 w-2 rounded-full bg-warn" aria-hidden />
        ) : null}
      </button>

      {open && (
        <div
          ref={panelRef}
          role="dialog"
          aria-label="Notifications"
          className="absolute right-0 top-12 z-50 w-[min(24rem,calc(100vw-2rem))] rounded-xl border border-line bg-panel shadow-xl"
        >
          <div className="flex items-center justify-between gap-2 border-b border-line px-4 py-3">
            <span className="text-sm font-bold text-ink">Notifications</span>
            <button
              type="button"
              onClick={markAll}
              disabled={unread === 0}
              className="inline-flex items-center gap-1 text-xs font-semibold text-brand disabled:text-muted disabled:opacity-60"
            >
              <CheckCheck size={13} /> Mark all as read
            </button>
          </div>

          {error && <p className="px-4 pt-3 text-xs text-bad">{error}</p>}

          {actions.length > 0 && (
            <div className="border-b border-line px-4 py-3">
              <div className="mb-2 text-[10px] font-bold uppercase tracking-wider text-muted">Needs your action</div>
              <ul className="space-y-1">
                {actions.map((item) => (
                  <li key={item.key}>
                    <Link
                      href={item.link}
                      onClick={() => setOpen(false)}
                      className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-ink hover:bg-soft"
                    >
                      <span className={`h-2 w-2 shrink-0 rounded-full ${SEVERITY_DOT[item.severity] ?? "bg-info"}`} aria-hidden />
                      {item.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="max-h-80 overflow-y-auto px-2 py-2">
            {recent === null ? (
              <div className="flex justify-center py-6 text-muted"><Loader2 size={16} className="animate-spin" /></div>
            ) : recent.length === 0 ? (
              <p className="px-2 py-6 text-center text-xs text-muted">You&apos;re all caught up.</p>
            ) : (
              <ul className="space-y-0.5">
                {recent.map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      onClick={() => openItem(item)}
                      className={`flex w-full items-start gap-2.5 rounded-lg px-2 py-2 text-left hover:bg-soft ${item.read ? "" : "bg-brand/5"}`}
                    >
                      <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${item.read ? "bg-line" : SEVERITY_DOT[item.severity] ?? "bg-info"}`} aria-hidden />
                      <span className="min-w-0 flex-1">
                        <span className={`block text-sm ${item.read ? "text-muted" : "font-semibold text-ink"}`}>{item.title}</span>
                        {item.body && <span className="block truncate text-xs text-muted">{item.body}</span>}
                        <span className="block text-[10px] text-muted">{formatWhen(item.created_at)}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="border-t border-line px-4 py-2.5 text-center">
            <Link href="/notifications" onClick={() => setOpen(false)} className="text-xs font-semibold text-brand hover:underline">
              View all notifications
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
