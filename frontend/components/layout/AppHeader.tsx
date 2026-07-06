"use client";

import { Settings, Bell } from "lucide-react";
import { RoleSwitcher } from "@/components/shell/RoleSwitcher";
import { NavSearch } from "@/components/shell/NavSearch";

export function BrandMark({ className = "h-14 w-14" }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={`${className} shrink-0`} role="img" aria-label="ZoikoLogia logo">
      <rect x="4" y="4" width="56" height="56" rx="16" fill="#16799A" />
      <rect x="17" y="18" width="31" height="30" rx="2" fill="none" stroke="#fff" strokeWidth="4" />
      <rect x="24" y="25" width="5" height="16" fill="#F3C437" />
      <rect x="32" y="25" width="5" height="16" fill="#F3C437" />
      <rect x="40" y="25" width="5" height="16" fill="#F3C437" />
    </svg>
  );
}

export function AppHeader() {
  return (
    <div className="m-4 mb-0 rounded-2xl border border-line bg-panel shadow-[0_1px_2px_rgba(16,24,40,0.04)] px-5 py-3.5 flex items-center gap-4">
      <NavSearch />

      <div className="flex items-center gap-3 justify-end shrink-0 ml-auto">
        <RoleSwitcher />
        <button className="h-10 w-10 flex items-center justify-center rounded-xl border border-line bg-panel text-muted hover:bg-soft">
          <Settings size={17} />
        </button>
        <button className="relative h-10 w-10 flex items-center justify-center rounded-xl border border-line bg-panel text-muted hover:bg-soft">
          <Bell size={17} />
          <span className="absolute top-2 right-2 h-2 w-2 rounded-full bg-gold" />
        </button>
      </div>
    </div>
  );
}
