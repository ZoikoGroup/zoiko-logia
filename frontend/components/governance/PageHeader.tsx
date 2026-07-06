"use client";

import { Pill } from "./Pill";
import { useRole } from "@/components/shell/RoleProvider";

export function PageHeader({ title, subtitle }: { title: string; subtitle: string }) {
  const { role } = useRole();

  return (
    <div className="rounded-2xl border border-line bg-panel shadow-[0_1px_2px_rgba(16,24,40,0.04)] p-5 flex flex-wrap items-start justify-between gap-4 mb-4">
      <div>
        <div className="text-xs text-muted mb-1">ZL-T2-05 / Production governance control surface</div>
        <h1 className="text-2xl font-extrabold text-ink tracking-tight">{title}</h1>
        <p className="mt-1.5 text-sm text-muted max-w-2xl">{subtitle}</p>
      </div>
      <div className="flex flex-wrap gap-2 justify-end">
        <Pill>Tenant: Zoiko Group</Pill>
        <Pill>Role: {role}</Pill>
        <Pill>Env: Staging → Prod</Pill>
      </div>
    </div>
  );
}
