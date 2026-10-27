"""Financial statements — Document 04 (ZL-FSR-ENG-004): source data integrity,
trial balance reconciliation and accounting classification.

Pipeline: receive (immutable source manifest, SHA-256, active content
rejected) → parse (every sheet, hidden content, formulas, cell positions) →
normalise (exact Decimal debit/credit, blank vs zero vs invalid, units,
currency) → integrity (balance, duplicates, missing codes, suspense, sign
anomalies, control totals) → classify (suggested statement line per account;
name-only classifications need evidence) → propose journals (balanced,
before/after effect, never posted) → approve (independent reviewer; frozen,
hashed snapshot).

Kriton proposes and explains; this deterministic engine calculates and
validates; only an authorised person approves. Nothing here alters the
uploaded source or posts to a ledger. Persistence of manifests, decisions and
snapshots is a later step (it needs a database migration).
"""
