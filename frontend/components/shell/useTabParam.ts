"use client";

import { useCallback } from "react";
import { usePathname, useSearchParams } from "next/navigation";

/** The active tab, kept in the URL (?tab=…) so menu links, search results
 * and redirects from merged pages can open a specific tab. Components using
 * this must sit inside a <Suspense> boundary (useSearchParams). */
export function useTabParam(defaultTab: string, tabs: readonly string[]): [string, (tab: string) => void] {
  const params = useSearchParams();
  const pathname = usePathname();
  const requested = params.get("tab");
  const active = requested && tabs.includes(requested) ? requested : defaultTab;

  const setTab = useCallback((tab: string) => {
    // Tabs are client state. Next's native history integration updates
    // useSearchParams immediately without fetching another server page.
    const next = new URLSearchParams(window.location.search);
    if (tab === defaultTab) next.delete("tab");
    else next.set("tab", tab);
    const query = next.toString();
    window.history.replaceState(null, "", `${query ? `${pathname}?${query}` : pathname}${window.location.hash}`);
  }, [defaultTab, pathname]);

  return [active, setTab];
}
