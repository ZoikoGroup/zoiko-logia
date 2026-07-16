"use client";

import { Bell, ChevronDown, Menu, Moon, Sun } from "lucide-react";
import { RoleSwitcher } from "@/components/shell/RoleSwitcher";
import { NavSearch } from "@/components/shell/NavSearch";
import { useTheme } from "@/components/shell/ThemeProvider";

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

export function AppHeader({ onMenuClick }: { onMenuClick?: () => void }) {
  const { theme, toggleTheme } = useTheme();

  return (
    <header className="mx-4 mt-4 grid min-h-16 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 rounded-2xl border border-line bg-panel p-2.5 shadow-[0_1px_2px_rgba(16,24,40,0.04)] sm:gap-3 sm:px-3">
      <button
        onClick={onMenuClick}
        aria-label="Open menu"
        className="lg:hidden h-10 w-10 flex items-center justify-center rounded-xl border border-line bg-panel text-muted hover:bg-soft shrink-0"
      >
        <Menu size={17} />
      </button>

      <div className="min-w-0 md:max-w-xl"><NavSearch /></div>

      <div className="flex shrink-0 items-center justify-end gap-1 sm:gap-1.5">
        <div className="hidden lg:block"><RoleSwitcher /></div>
        <button
          onClick={toggleTheme}
          aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          className="flex h-10 w-10 items-center justify-center rounded-xl text-muted hover:bg-soft"
        >
          {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
        </button>
        <button aria-label="Notifications" className="relative flex h-10 w-10 items-center justify-center rounded-xl text-muted hover:bg-soft">
          <Bell size={19} />
          <span className="absolute right-1.5 top-1 grid h-4 min-w-4 place-items-center rounded-full bg-bad px-1 text-[9px] font-bold text-white">3</span>
        </button>
        <button aria-label="Open user menu" className="ml-0.5 flex h-10 items-center gap-2 rounded-xl border border-transparent px-1 hover:border-line hover:bg-soft sm:px-2">
          <span className="grid h-8 w-8 place-items-center rounded-full bg-brand text-xs font-bold text-white">LM</span>
          <span className="hidden text-left xl:block"><strong className="block text-xs text-ink">Lennox M.</strong><small className="block text-[10px] text-muted">Administrator</small></span>
          <ChevronDown size={14} className="hidden text-muted sm:block" />
        </button>
      </div>

      <div className="col-span-3 lg:hidden">
        <RoleSwitcher />
      </div>
    </header>
  );
}
