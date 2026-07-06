import { FOOTER_NOTE } from "@/lib/governance-data";

export function FooterNote() {
  return (
    <p className="mt-6 rounded-2xl border border-line bg-panel shadow-[0_1px_2px_rgba(16,24,40,0.04)] p-4 text-xs text-muted leading-relaxed">
      {FOOTER_NOTE}
    </p>
  );
}
