export type Theme = "light" | "dark";

export const THEME_COOKIE = "zoiko_theme";

/** Appearance choices kept per browser (applied before first paint by the
 * init script in app/layout.tsx, as data attributes on <html>). */
export type TextSize = "normal" | "large";
export const TEXT_SIZE_COOKIE = "zoiko_text_size";
export const REDUCE_MOTION_COOKIE = "zoiko_reduce_motion";
