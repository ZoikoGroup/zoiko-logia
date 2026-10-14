"use client";

import { useCallback } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

/** The active tab, kept in the URL (?tab=…) so menu links, search results
 * and redirects from merged pages can open a specific tab. Components using
 * this must sit inside a <Suspense> boundary (useSearchParams). */
export function useTabParam(defaultTab: string, tabs: readonly string[]): [string, (tab: string) => void] {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const requested = params.get("tab");
  const active = requested && tabs.includes(requested) ? requested : defaultTab;

  const setTab = useCallback((tab: string) => {
    const next = new URLSearchParams(params.toString());
    if (tab === defaultTab) next.delete("tab");
    else next.set("tab", tab);
    const query = next.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }, [defaultTab, params, pathname, router]);

  return [active, setTab];
}
