"""Method notes for accounting and audit calculations the model got wrong.

Each note is added to the prompt only when the question is about its topic.
It states the method, never the answer: the model still works the user's own
figures with the calculator. Found in the 23 Oct 2026 manual review, where
the arithmetic was right and the method was not:

- an operating lease's Year-1 expense given as depreciation plus interest
  ($54,760.68) instead of ASC 842's single straight-line cost ($50,000);
- dollar-value LIFO layers all priced at the current index ($430,000)
  instead of each at its own year's index ($350,500);
- diluted EPS on convertibles by the treasury-stock method ($2.37, above
  basic) instead of if-converted ($2.11);
- a PPS sample size multiplied by the expansion factor with no expected
  misstatement (96 items) instead of 60, and the projected misstatement;
- a consolidation entry debiting the subsidiary's net assets as an asset;
- a licence delivered on the contract date left wholly in deferred revenue.
"""
from __future__ import annotations

import re

_I = re.I


def _all(*patterns: str):
    compiled = [re.compile(pattern, _I) for pattern in patterns]
    return lambda question: all(pattern.search(question) for pattern in compiled)


_NOTES: tuple[tuple[object, str], ...] = (
    (_all(r"\boperating\s+leases?\b", r"\b(?:right[- ]of[- ]use|ROU|lease\s+liabilit|lease\s+expense|lessee)"),
     "Operating lease (lessee): unless the question names IFRS 16, apply US GAAP ASC 842. Lease expense is "
     "one straight-line cost each year: total lease payments ÷ lease term. It is not split into depreciation "
     "and interest. The lease liability still accrues interest at the discount rate and is reduced by each "
     "payment. The right-of-use asset is reduced by the straight-line expense minus that year's interest on "
     "the liability. Under IFRS 16 a lessee has no operating-lease classification: depreciation of the "
     "right-of-use asset plus interest on the liability."),
    (_all(r"\bdollar[- ]value\s+LIFO\b"),
     "Dollar-value LIFO: deflate each year-end inventory to base-year cost by dividing by that year's index. "
     "A layer is the increase in base-year cost over the previous year; a decrease erodes the most recent "
     "layers first. Ending inventory is each surviving layer at base-year cost multiplied by the index of the "
     "year that layer was added (the base layer at 1.00), summed. Never price every layer at the current "
     "year's index."),
    (_all(r"\bdiluted\s+(?:EPS|earnings\s+per\s+share)\b", r"\bconvertible\b"),
     "Diluted EPS with convertible securities uses the if-converted method, not the treasury-stock method "
     "(which is for options and warrants). Basic EPS deducts the year's dividend on cumulative preferred "
     "stock, declared or not. For each convertible, incremental EPS = earnings effect ÷ shares issued on "
     "conversion: for convertible preferred, the preferred dividend added back; for convertible bonds, "
     "interest × (1 − tax rate). Include the securities in order from the lowest incremental EPS, and include "
     "each only while its incremental EPS is below the running EPS before it is added (otherwise it is "
     "antidilutive). "
     "Diluted EPS can never exceed basic EPS."),
    (_all(r"\b(?:probability[- ]proportional[- ]to[- ]size|PPS|monetary[- ]unit\s+sampling|MUS)\b",
          r"\b(?:sample\s+size|sampling\s+interval|tainting|projected\s+misstatement)\b"),
     "Monetary-unit (PPS) sampling: sample size = book value × reliability factor ÷ (tolerable misstatement − "
     "expected misstatement × expansion factor). The expansion factor multiplies only an expected misstatement; "
     "if none is given, the expected misstatement is zero and the expansion factor is not used. Sampling "
     "interval = book value ÷ sample size. For a logical unit whose book value is below the sampling interval: "
     "tainting = (book value − audited value) ÷ book value, and projected misstatement = tainting × sampling "
     "interval. A unit at or above the interval projects its actual misstatement."),
    (_all(r"\b(?:eliminat\w*|consolidat\w*)\b", r"\b(?:acqui\w+|subsidiar\w+|goodwill|parent)\b"),
     "Consolidation elimination at acquisition: debit the subsidiary's equity accounts (they equal its book "
     "net assets), debit each fair-value adjustment to its own account (the asset uplift, an unrecorded "
     "intangible such as a trade name), credit a recognised contingent liability, debit goodwill (or credit a "
     "bargain-purchase gain), and credit the parent's investment in the subsidiary. Do not record the "
     "subsidiary's book net assets as an asset."),
    (_all(r"\b(?:performance\s+obligations?|stand-?\s?alone\s+selling\s+prices?|transaction\s+price)\b",
          r"\bjournal\s+entr"),
     "Revenue from contracts: a journal entry on a given date recognises revenue only for performance "
     "obligations already satisfied on that date (for example, a licence or equipment delivered that day). "
     "An obligation completed later, even a few weeks later such as installation finished at month-end, is "
     "not revenue on the earlier date: cash received for it, and for services still to be performed, is a "
     "contract liability (deferred revenue) until it is satisfied."),
)


_JOURNAL_ASKED = re.compile(r"\b(?:journal\s+entr\w*|entries|record\s+the|book\s+the|double\s+entry)\b", re.I)
NO_UNREQUESTED_ENTRIES = ("Answer only the parts the question asks for: do not add journal entries, conversion entries "
                          "or disclosure tables it does not request.")


def accounting_method_guidance(question: str) -> str:
    """The method notes for the topics this question is about, or ""."""
    notes = [note for applies, note in _NOTES if applies(question or "")]
    if not notes:
        return ""
    if not _JOURNAL_ASKED.search(question or ""):
        # Two EPS answers added conversion and dividend entries nobody asked
        # for, one of them backwards (23 Oct 2026).
        notes.append(NO_UNREQUESTED_ENTRIES)
    return ("\n\nMethod notes for this question (apply them to the figures given; they are standard practice, "
            "not a source to cite):\n- " + "\n- ".join(notes))
