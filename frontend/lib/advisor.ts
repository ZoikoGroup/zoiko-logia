/**
 * Centralized advisor-facing strings, per ZL-ENG-01 two-tier naming rule:
 *
 *   Kriton™     — the only user-facing advisor name. Use everywhere in UI,
 *                 chat, notifications, tooltips, error states, help docs.
 *   The internal knowledge, source, evidence and provenance layer is never
 *   named on any customer-facing surface — no exceptions.
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
} as const;
