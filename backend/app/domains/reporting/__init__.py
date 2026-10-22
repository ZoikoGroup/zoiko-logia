"""Financial reporting — ZL-RPT-007 gates G1 (read-only source truth) and G2
(deterministic financial compiler).

Ledger input → sealed snapshot → typed decimal facts → primary statements →
reconcilers. Everything here is deterministic: no model calls, no float
arithmetic, no rounding before presentation. Kriton may later narrate these
facts (G4); it never computes them.

The most a report produced here can reach is DRAFT_RECONCILED. Review,
approval and issue (G6) are separate gates with separate controls.
"""
