"use client";

import { createContext, useContext, useSyncExternalStore, ReactNode } from "react";
import { Theme, THEME_COOKIE } from "@/lib/theme";
import { readCookie, subscribeCookies, writeCookie } from "@/lib/cookie-store";

type ThemeContextValue = {
  theme: Theme;
  toggleTheme: () => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readThemeCookie(): Theme | null {
  return readCookie(THEME_COOKIE) as Theme | null;
}

function systemPrefersDark(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function currentTheme(): Theme {
  return readThemeCookie() ?? (systemPrefersDark() ? "dark" : "light");
}

function serverTheme(): Theme {
  return "light";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  // "light" during SSR/hydration, then the saved cookie (or the system
  // preference) — read as an external store rather than copied into state
  // from an effect.
  const theme = useSyncExternalStore(subscribeCookies, currentTheme, serverTheme);

  function applyTheme(next: Theme) {
    document.documentElement.setAttribute("data-theme", next);
    writeCookie(THEME_COOKIE, next, 60 * 60 * 24 * 365);
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
