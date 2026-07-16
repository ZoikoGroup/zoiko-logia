"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";
import { NAV_SECTIONS, isVisible, navHref } from "@/lib/nav";
import { useRole } from "./RoleProvider";

type Result = {
  label: string;
  href: string;
  sectionLabel: string;
  icon: React.ComponentType<{ size?: number }>;
};

export function NavSearch() {
  const { role } = useRole();
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  const allItems: Result[] = useMemo(() => {
    const items: Result[] = [];
    for (const section of NAV_SECTIONS) {
      if (!isVisible(section.allowedRoles, role)) continue;
      for (const item of section.items) {
        if (!isVisible(item.allowedRoles, role)) continue;
        items.push({ label: item.label, href: navHref(item.slug), sectionLabel: section.label, icon: item.icon });
      }
    }
    return items;
  }, [role]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return allItems.filter((item) => item.label.toLowerCase().includes(q)).slice(0, 8);
  }, [query, allItems]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  function goTo(href: string) {
    router.push(href);
    setQuery("");
    setOpen(false);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      setOpen(false);
      return;
    }
    if (!results.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => (i + 1) % results.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => (i - 1 + results.length) % results.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      goTo(results[activeIndex].href);
    }
  }

  return (
    <div ref={containerRef} className="relative w-full">
      <div className="zl-search-surface flex items-center gap-2 rounded-xl border px-3.5 py-2.5 transition-shadow">
        <Search size={16} className="text-brand shrink-0" />
        <input
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActiveIndex(0);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={handleKeyDown}
          placeholder="Search modules, policies, sources..."
          className="w-full min-w-0 bg-transparent text-sm text-ink placeholder:text-muted outline-none"
        />
      </div>

      {open && query.trim() && (
        <div className="absolute left-0 right-0 mt-2 rounded-xl border border-line bg-panel shadow-[0_10px_28px_rgba(11,95,122,0.12)] py-1.5 z-20 max-h-80 overflow-y-auto">
          {results.length === 0 ? (
            <div className="px-3.5 py-2.5 text-sm text-muted">No pages match &ldquo;{query}&rdquo;.</div>
          ) : (
            results.map((item, i) => (
              <button
                key={item.href}
                onClick={() => goTo(item.href)}
                onMouseEnter={() => setActiveIndex(i)}
                className={`w-full flex items-center gap-2.5 px-3.5 py-2.5 text-left text-sm ${
                  i === activeIndex ? "bg-soft text-ink" : "text-ink"
                }`}
              >
                <item.icon size={15} />
                <span className="flex-1 truncate">{item.label}</span>
                <span className="text-[11px] text-muted shrink-0">{item.sectionLabel}</span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
