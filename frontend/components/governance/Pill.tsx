import { ReactNode } from "react";

const TONE_TEXT: Record<string, string> = {
  neutral: "text-muted",
  ok: "text-ok",
  warn: "text-warn",
  bad: "text-bad",
  info: "text-info",
};

export function Pill({
  tone = "neutral", children,
}: {
  tone?: "neutral" | "ok" | "warn" | "bad" | "info";
  children: ReactNode;
}) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border border-line bg-chip px-2 py-0.5 text-[11px] font-medium ${TONE_TEXT[tone]}`}>
      {children}
    </span>
  );
}
