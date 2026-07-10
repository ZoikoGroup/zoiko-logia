import { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

export type PanelTone = "brand" | "ok" | "warn" | "bad" | "info";

export const PANEL_CLASS =
  "rounded-lg border border-line bg-panel/75 backdrop-blur-md p-5 shadow-[0_12px_30px_rgba(0,0,0,0.02)]";

const ICON_BADGE_STYLE: Record<PanelTone, string> = {
  brand: "bg-brand/10 border-brand/20 text-brand",
  ok: "bg-ok/10 border-ok/20 text-ok",
  warn: "bg-warn/10 border-warn/20 text-warn",
  bad: "bg-bad/10 border-bad/20 text-bad",
  info: "bg-info/10 border-info/20 text-info",
};

export function PanelHeader({
  icon: Icon, tone = "brand", title, subtitle, action,
}: {
  icon: LucideIcon;
  tone?: PanelTone;
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-2 border-b border-line/50 pb-4 mb-4">
      <div className="flex items-center gap-2">
        <div className={`p-1.5 rounded-md border ${ICON_BADGE_STYLE[tone]}`}>
          <Icon size={14} />
        </div>
        <div>
          <h3 className="text-sm font-bold text-ink">{title}</h3>
          {subtitle && <p className="text-[11px] text-muted">{subtitle}</p>}
        </div>
      </div>
      {action}
    </div>
  );
}
