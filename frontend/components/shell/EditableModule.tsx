import type { LucideIcon } from "lucide-react";
import { CheckCircle2, Clock3, Filter, Plus, Save, Search, SlidersHorizontal } from "lucide-react";
import { PHASE_LABELS } from "@/lib/phases";
import { Pill } from "@/components/governance/Pill";
import { PanelHeader, PANEL_CLASS, type PanelTone } from "@/components/governance/PanelHeader";
import { StatTile } from "@/components/governance/StatTile";

type StatusTone = "ok" | "warn" | "bad" | "neutral";

type Stat = {
  label: string;
  value: string | number;
  tone: PanelTone;
  icon: LucideIcon;
};

type RecordItem = {
  title: string;
  meta: string;
  status: string;
  tone: StatusTone;
};

type Field = {
  label: string;
  value: string;
  type?: "input" | "select" | "textarea";
};

export function EditableModule({
  phase,
  description,
  icon: Icon,
  panelTitle,
  primaryAction,
  stats,
  records,
  fields,
  checklist,
}: {
  phase: number;
  description: string;
  icon: LucideIcon;
  panelTitle: string;
  primaryAction: string;
  stats: Stat[];
  records: RecordItem[];
  fields: Field[];
  checklist: string[];
}) {
  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-brand/25 bg-brand/5 p-4">
        <div className="text-sm font-bold text-ink">Editable module workspace</div>
        <p className="mt-1 text-xs text-muted">
          This replaces the planned-module placeholder with a working page layout for records, filters, editing, and readiness checks.
        </p>
      </div>

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
        {stats.map((stat) => (
          <StatTile key={stat.label} {...stat} />
        ))}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1.15fr_.85fr] gap-4">
        <section className={PANEL_CLASS}>
          <PanelHeader
            icon={Icon}
            title={panelTitle}
            subtitle={`Phase ${phase}: ${PHASE_LABELS[phase]}`}
            action={
              <button className="inline-flex items-center gap-1.5 rounded-lg border border-brand/30 bg-brand px-3 py-2 text-xs font-bold text-white hover:bg-brand-2">
                <Plus size={14} />
                {primaryAction}
              </button>
            }
          />

          <div className="mb-4 grid grid-cols-1 sm:grid-cols-[1fr_auto_auto] gap-2">
            <label className="relative block">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-brand" />
              <input
                className="zl-search-surface w-full rounded-lg border py-2 pl-9 pr-3 text-sm text-ink outline-none focus:border-brand"
                placeholder="Search records"
              />
            </label>
            <button className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-line bg-panel px-3 py-2 text-xs font-bold text-ink hover:bg-soft">
              <Filter size={14} />
              Filter
            </button>
            <button className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-line bg-panel px-3 py-2 text-xs font-bold text-ink hover:bg-soft">
              <SlidersHorizontal size={14} />
              View
            </button>
          </div>

          <div className="overflow-hidden rounded-lg border border-line">
            <div className="grid grid-cols-[1fr_auto] bg-soft px-3 py-2 text-[11px] font-bold uppercase text-muted">
              <span>Record</span>
              <span>Status</span>
            </div>
            {records.map((record) => (
              <div key={record.title} className="grid grid-cols-[1fr_auto] gap-3 border-t border-line px-3 py-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-ink">{record.title}</div>
                  <div className="mt-0.5 text-xs text-muted">{record.meta}</div>
                </div>
                <Pill tone={record.tone}>{record.status}</Pill>
              </div>
            ))}
          </div>
        </section>

        <section className={PANEL_CLASS}>
          <PanelHeader
            icon={Save}
            tone="ok"
            title="Edit workspace"
            subtitle={description}
            action={
              <button className="inline-flex items-center gap-1.5 rounded-lg border border-ok/25 bg-ok/10 px-3 py-2 text-xs font-bold text-ok hover:bg-ok/15">
                <Save size={14} />
                Save
              </button>
            }
          />

          <form className="space-y-3">
            {fields.map((field) => (
              <label key={field.label} className="block">
                <span className="mb-1 block text-xs font-bold text-muted">{field.label}</span>
                {field.type === "textarea" ? (
                  <textarea
                    className="min-h-24 w-full resize-none rounded-lg border border-line bg-bg px-3 py-2 text-sm text-ink outline-none focus:border-brand"
                    defaultValue={field.value}
                  />
                ) : field.type === "select" ? (
                  <select
                    className="w-full rounded-lg border border-line bg-bg px-3 py-2 text-sm text-ink outline-none focus:border-brand"
                    defaultValue={field.value}
                  >
                    <option>{field.value}</option>
                    <option>Draft</option>
                    <option>Under review</option>
                    <option>Approved</option>
                    <option>Blocked</option>
                  </select>
                ) : (
                  <input
                    className="w-full rounded-lg border border-line bg-bg px-3 py-2 text-sm text-ink outline-none focus:border-brand"
                    defaultValue={field.value}
                  />
                )}
              </label>
            ))}
          </form>

          <div className="mt-4 rounded-lg border border-line bg-bg p-3">
            <div className="mb-2 text-xs font-bold text-muted">Readiness checklist</div>
            <div className="space-y-2">
              {checklist.map((item, index) => (
                <label key={item} className="flex items-center gap-2 text-sm text-ink">
                  <input type="checkbox" className="h-4 w-4 accent-brand" defaultChecked={index < 2} />
                  <span>{item}</span>
                </label>
              ))}
            </div>
          </div>
        </section>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {[
          { icon: CheckCircle2, label: "Validation", text: "Required fields and approvals are checked before promotion." },
          { icon: Clock3, label: "Timeline", text: "Recent changes stay visible beside the editable record state." },
          { icon: Save, label: "Draft safety", text: "Edits can be staged before they affect production controls." },
        ].map((item) => (
          <div key={item.label} className="rounded-lg border border-line bg-panel p-4">
            <item.icon size={16} className="text-brand" />
            <div className="mt-2 text-sm font-bold text-ink">{item.label}</div>
            <p className="mt-1 text-xs text-muted">{item.text}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
