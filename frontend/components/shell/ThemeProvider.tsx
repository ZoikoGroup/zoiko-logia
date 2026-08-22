"use client";

import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { Theme, THEME_COOKIE } from "@/lib/theme";

type ThemeContextValue = {
  theme: Theme;
  toggleTheme: () => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readResolvedTheme(): Theme {
  // The inline script in layout.tsx (THEME_INIT_SCRIPT) runs before hydration
  // and already sets this attribute — read it back rather than re-deriving
  // independently from the cookie/prefers-color-scheme here. Two separate
  // computations of "what theme should this be" can disagree (e.g. if the
  // OS-level dark-mode signal isn't perfectly stable between the script's
  // run and this effect's), which reads as the background randomly flipping
  // between loads. The DOM attribute the script set is the single source of
  // truth for what was actually painted.
  if (typeof document === "undefined") return "light";
  const attr = document.documentElement.getAttribute("data-theme");
  return attr === "dark" ? "dark" : "light";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>("light");

  useEffect(() => {
    const timer = window.setTimeout(() => setThemeState(readResolvedTheme()), 0);
    return () => window.clearTimeout(timer);
  }, []);

  function applyTheme(next: Theme) {
    document.documentElement.setAttribute("data-theme", next);
    document.cookie = `${THEME_COOKIE}=${next}; path=/; max-age=${60 * 60 * 24 * 365}`;
    setThemeState(next);
  }

  function toggleTheme() {
    applyTheme(theme === "dark" ? "light" : "dark");
  }

  return <ThemeContext.Provider value={{ theme, toggleTheme }}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within a ThemeProvider");
  return ctx;
}
