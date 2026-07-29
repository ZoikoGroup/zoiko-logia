"""Governed internal educational procedure for routine bank reconciliation."""
from __future__ import annotations


BANK_RECONCILIATION_GOVERNED_SOURCE_ID = "src-kriton-bank-reconciliation-procedure"
BANK_RECONCILIATION_NODE_PREFIX = "bank-reconciliation-procedure-"

_PROCEDURE_TEXT = """Kriton Bank Reconciliation Educational Procedure, version 1.0.

Purpose: A bank reconciliation compares the cash balance in the accounting
records with the corresponding bank statement, explains timing differences and
errors, records book-side adjustments, and confirms that the adjusted balances
agree. It detects discrepancies; it does not by itself prevent every future error.

Procedure:
1. Select the reconciliation period and obtain the bank statement and the cash
   ledger or cash-book activity for that same period.
2. Confirm that the opening book balance agrees with the prior completed
   reconciliation.
3. Match deposits, withdrawals, cleared checks, transfers, direct debits, and
   other transactions between the bank statement and the accounting records.
4. Identify timing differences, including deposits in transit and outstanding
   checks that have been recorded in the books but have not cleared the bank.
5. Identify bank-only items not yet recorded in the books, including bank fees,
   interest, automatic payments, returned items, and direct credits or debits.
6. Investigate bank errors and bookkeeping errors, including omissions,
   duplicates, transpositions, and incorrect amounts.
7. Calculate an adjusted bank balance for timing differences and an adjusted
   book balance for bank-only items and book errors.
8. Post the necessary journal entries for book-side adjustments. Timing
   differences already recorded in the books normally do not require another
   journal entry merely because they have not cleared the bank.
9. Verify that the adjusted bank balance equals the adjusted book balance.
10. Document the reconciliation, retain supporting evidence, and obtain any
    review or approval required by the entity's control procedures.

Perform reconciliations regularly. Monthly reconciliation is common, but the
appropriate frequency depends on transaction volume, risk, and the entity's
control policy. A credit-card statement is not normally part of a bank-account
reconciliation unless the specific account activity requires it.
"""


def to_bank_reconciliation_rag_chunk() -> dict:
    return {
        "text": _PROCEDURE_TEXT,
        "metadata": {
            "source_id": BANK_RECONCILIATION_GOVERNED_SOURCE_ID,
            "title": "Kriton Bank Reconciliation Educational Procedure",
            "version": "1.0",
            "jurisdiction": "GLOBAL",
        },
        "score": 1.0,
        "node_id": f"{BANK_RECONCILIATION_NODE_PREFIX}v1",
    }
