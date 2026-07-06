"use client";

type Tab = { label: string; slug: string };

export function Tabs({
  tabs, activeSlug, onChange,
}: {
  tabs: Tab[];
  activeSlug: string;
  onChange: (slug: string) => void;
}) {
  return (
    <div role="tablist" className="flex flex-wrap gap-1 border-b border-line mb-4">
      {tabs.map((tab) => {
        const active = tab.slug === activeSlug;
        return (
          <button
            key={tab.slug}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(tab.slug)}
            className={`px-3.5 py-2 text-sm font-medium border-b-2 -mb-px ${
              active ? "border-brand text-ink" : "border-transparent text-muted hover:text-ink"
            }`}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
