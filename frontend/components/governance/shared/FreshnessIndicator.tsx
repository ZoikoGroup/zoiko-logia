import { CircleAlert, CircleCheck, CircleHelp, TimerReset } from "lucide-react";
import type { FreshnessState } from "@/types/governance";

const FRESHNESS_META: Record<FreshnessState, { label: string; icon: typeof CircleCheck; tone: string }> = {
  CURRENT: { label: "Current", icon: CircleCheck, tone: "text-ok" },
  DELAYED: { label: "Delayed", icon: TimerReset, tone: "text-warn" },
  STALE: { label: "Stale", icon: CircleAlert, tone: "text-bad" },
  UNKNOWN: { label: "Unknown", icon: CircleHelp, tone: "text-muted" },
};

export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const now = Date.now();
  const diffMs = now - then;
  const minutes = Math.round(diffMs / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

export function FreshnessIndicator({ state, at }: { state: FreshnessState; at: string }) {
  const meta = FRESHNESS_META[state];
  const Icon = meta.icon;
  const absolute = new Date(at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-xs font-medium ${meta.tone}`}
      title={`${meta.label} · ${absolute}`}
      tabIndex={0}
    >
      <Icon size={13} />
      {meta.label} · {relativeTime(at)}
    </span>
  );
}
