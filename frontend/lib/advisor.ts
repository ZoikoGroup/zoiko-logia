/**
 * Centralized advisor-facing strings, per ZL-ENG-01 two-tier naming rule:
 *
 *   Kriton™     — the only user-facing advisor name. Use everywhere in UI,
 *                 chat, notifications, tooltips, error states, help docs.
 *   Massarius™  — the backend/reasoning engine name. Never shown to users
 *                 except via ADVISOR.about.engineLine, and only inside an
 *                 About/Info panel or architecture section. Nowhere else.
 *
 * Do not hardcode advisor copy in components — import from here so the
 * naming rule stays enforceable in one place.
 */
export const ADVISOR = {
  displayName: "Kriton™",
  navLabel: "Ask Kriton™",
  chatPlaceholder: "Ask Kriton™ about a standard, figure, source or disclosure.",
  emptyState: "Kriton™ is ready when you are.",
  loadingState: "Kriton™ is reviewing sources...",
  errorState: "Kriton™ could not complete this request.",
  tooltip: {
    default: "Ask Kriton™ about this figure, standard, or disclosure.",
  },
  about: {
    // Approved for use ONLY in an About/Info panel or architecture section.
    engineLine: "Kriton™ runs on Massarius™, ZoikoLogia's source-governed accounting intelligence engine.",
  },
} as const;
