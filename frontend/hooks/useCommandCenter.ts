"use client";

import { useEffect, useState } from "react";
import { ApiError, getAuthToken, getCommandCenter } from "@/lib/api";
import type { CommandCenterViewModel } from "@/lib/command-center-types";

/** Loads the signed-in user's home view once per mount. */
export function useCommandCenter(): { model: CommandCenterViewModel | null; error: string } {
  const [model, setModel] = useState<CommandCenterViewModel | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    getCommandCenter(getAuthToken(), controller.signal)
      .then(setModel)
      .catch((err) => {
        if (controller.signal.aborted) return;
        setError(err instanceof ApiError ? err.message : "Could not load your workspace. Please try again.");
      });
    return () => controller.abort();
  }, []);

  return { model, error };
}

/** "18 min ago", "3 h ago", "2 days ago", or a date for older items. */
export function timeAgo(iso: string | null, now: number = Date.now()): string {
  if (!iso) return "";
  // Whole elapsed units (floor), so 30 seconds is "just now", not "1 min ago".
  const minutes = Math.floor((now - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} day${days === 1 ? "" : "s"} ago`;
  return new Date(iso).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
}
