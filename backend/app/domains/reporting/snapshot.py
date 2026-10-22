"""Import and seal a ledger snapshot (ZL-RPT-007 §6.1 steps 04–06, gate G1).

Re-importing the same source yields the same snapshot hash. A retried journal
(same source_id, version and content) is counted once; a later version
supersedes the earlier one and is recorded; the same version with different
content is a conflict and stops the import. Journals after the cutoff are
excluded and counted, never silently dropped.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date

from .ledger import Account, Journal, LedgerError, parse_accounts, parse_journal

SNAPSHOT_SCHEMA_VERSION = "zl-rpt-snapshot/1"


@dataclass(frozen=True)
class ImportReceipt:
    received: int
    accepted: int
    duplicates_ignored: int
    superseded: tuple[str, ...]          # "source_id@version" replaced by a later version
    after_cutoff: tuple[str, ...]        # source_ids posted after the cutoff


@dataclass(frozen=True)
class SealedSnapshot:
    entity: str
    currency: str
    period_start: date
    period_end: date
    cutoff: date
    accounts: dict[str, Account]
    journals: tuple[Journal, ...]
    receipt: ImportReceipt
    snapshot_hash: str
    metadata: dict = field(default_factory=dict)


def _decimal_text(value) -> str:
    # Canonical text so 150000, 150000.00 and 1.5E+5 hash identically.
    text = format(value.normalize(), "f")
    return "0" if text in ("-0", "") else text


def _journal_canonical(journal: Journal) -> dict:
    return {
        "source_id": journal.source_id,
        "version": journal.version,
        "posted_on": journal.posted_on.isoformat(),
        "reverses": journal.reverses,
        "lines": [
            {"account": line.account, "debit": _decimal_text(line.debit), "credit": _decimal_text(line.credit)}
            for line in journal.lines
        ],
    }


def _hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def seal_snapshot(raw: dict) -> SealedSnapshot:
    """Validate, deduplicate, apply cutoff and seal one entity's ledger."""
    entity = str(raw.get("entity", "")).strip()
    currency = str(raw.get("currency", "")).strip().upper()
    if not entity or len(currency) != 3:
        raise LedgerError("context_invalid", "entity and a three-letter currency are required")
    try:
        period_start = date.fromisoformat(str(raw["period_start"]))
        period_end = date.fromisoformat(str(raw["period_end"]))
        cutoff = date.fromisoformat(str(raw.get("cutoff") or raw["period_end"]))
    except (KeyError, ValueError):
        raise LedgerError("period_invalid", "period_start, period_end (and optional cutoff) must be YYYY-MM-DD") from None
    if period_start > period_end or cutoff < period_end:
        raise LedgerError("period_invalid", "period_start must precede period_end, and cutoff cannot precede period_end")
    if raw.get("currencies") and set(raw["currencies"]) != {currency}:
        # Translation is a G3+ engine; a mixed-currency ledger is unsupported here.
        raise LedgerError("fx_missing_or_inapplicable", "only single-currency ledgers are supported")

    accounts = parse_accounts(raw.get("accounts") or [])
    if not any(account.is_cash for account in accounts.values()):
        raise LedgerError("account_invalid", "the chart of accounts has no cash account")

    received = list(raw.get("journals") or [])
    latest: dict[str, Journal] = {}
    duplicates = 0
    superseded: list[str] = []
    after_cutoff: list[str] = []
    for item in received:
        journal = parse_journal(item, accounts)
        held = latest.get(journal.source_id)
        if held is None or journal.version > held.version:
            if held is not None:
                superseded.append(f"{held.source_id}@{held.version}")
            latest[journal.source_id] = journal
        elif journal.version == held.version:
            if _journal_canonical(journal) != _journal_canonical(held):
                raise LedgerError("duplicate_conflict",
                                  f"{journal.source_id}@{journal.version} arrived twice with different content")
            duplicates += 1
        else:
            superseded.append(f"{journal.source_id}@{journal.version}")

    kept = []
    for journal in sorted(latest.values(), key=lambda j: (j.posted_on, j.source_id)):
        if journal.posted_on > cutoff:
            after_cutoff.append(journal.source_id)
        else:
            kept.append(journal)
    kept_ids = {journal.source_id for journal in kept}
    for journal in kept:
        if journal.reverses and journal.reverses not in kept_ids:
            raise LedgerError("reversal_orphan", f"{journal.source_id} reverses {journal.reverses}, which is not in the snapshot")

    receipt = ImportReceipt(
        received=len(received), accepted=len(kept), duplicates_ignored=duplicates,
        superseded=tuple(sorted(superseded)), after_cutoff=tuple(sorted(after_cutoff)),
    )
    snapshot_hash = _hash({
        "schema": SNAPSHOT_SCHEMA_VERSION,
        "entity": entity, "currency": currency,
        "period_start": period_start.isoformat(), "period_end": period_end.isoformat(),
        "cutoff": cutoff.isoformat(),
        "accounts": [
            {"code": a.code, "type": a.type, "is_cash": a.is_cash}
            for a in sorted(accounts.values(), key=lambda a: a.code)
        ],
        "journals": [_journal_canonical(j) for j in kept],
    })
    return SealedSnapshot(
        entity=entity, currency=currency, period_start=period_start, period_end=period_end,
        cutoff=cutoff, accounts=accounts, journals=tuple(kept), receipt=receipt,
        snapshot_hash=snapshot_hash, metadata=dict(raw.get("metadata") or {}),
    )
