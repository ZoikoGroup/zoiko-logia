import type { LucideIcon } from "lucide-react";
import type { PanelTone } from "./PanelHeader";

const TILE_STYLE: Record<PanelTone, { wrap: string; badge: string; text: string }> = {
  brand: { wrap: "border-brand/20 bg-brand/5", badge: "bg-brand/10 text-brand border-brand/20", text: "text-brand" },
  ok: { wrap: "border-ok/20 bg-ok/5", badge: "bg-ok/10 text-ok border-ok/20", text: "text-ok" },
  warn: { wrap: "border-warn/20 bg-warn/5", badge: "bg-warn/10 text-warn border-warn/20", text: "text-warn" },
  bad: { wrap: "border-bad/20 bg-bad/5", badge: "bg-bad/10 text-bad border-bad/20", text: "text-bad" },
  info: { wrap: "border-info/20 bg-info/5", badge: "bg-info/10 text-info border-info/20", text: "text-info" },
};

export function StatTile({
  label, value, tone, icon: Icon,
}: {
  label: string;
  value: string | number;
  tone: PanelTone;
  icon: LucideIcon;
}) {
  const s = TILE_STYLE[tone];
  return (
    <div
      className={`rounded-lg border bg-panel/85 p-4 flex flex-col justify-between shadow-[0_4px_12px_rgba(0,0,0,0.01)] transition-all duration-300 ${s.wrap} hover:-translate-y-0.5 hover:shadow-lg`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] text-muted font-bold uppercase tracking-wider">{label}</span>
        <div className={`p-1.5 rounded-md border ${s.badge}`}>
          <Icon size={13} />
        </div>
      </div>
      <div className={`text-2xl font-extrabold tracking-tight mt-3 ${s.text}`}>{value}</div>
    </div>
  );
}
