"""Compliance Calendar: statutory filing and payment deadlines, from rules.

Each rule is a published, general deadline with its official source. The
calendar lists every occurrence in a window. It is NOT client-specific:
VAT staggers, accounting year ends, QRMP schemes, extensions announced by
notification and bank holidays all vary, so each item says what it assumes
and points to the source. A date on a weekend is flagged with that
authority's rule rather than silently moved.

Rules (checked against the linked guidance, October 2026):
  UK   VAT return and payment (MTD): 1 calendar month + 7 days after the
       VAT period ends; calendar-quarter periods assumed.
  UK   PAYE / NIC (electronic): 22nd after the tax month ending on the 5th.
  UK   Self Assessment: online return and balancing payment 31 January;
       second payment on account 31 July.
  IN   GSTR-1 (monthly filers): 11th of the next month.
  IN   GSTR-3B (monthly filers): 20th of the next month.
  IN   TDS deposit: 7th of the next month; for March, 30 April.
  IN   TDS returns (24Q/26Q): 31 Jul, 31 Oct, 31 Jan, 31 May.
  IN   Advance tax: 15 Jun, 15 Sep, 15 Dec, 15 Mar.
  US   Estimated tax (Form 1040-ES): 15 Apr, 15 Jun, 15 Sep, 15 Jan.
  US   Form 941 (quarterly payroll): 30 Apr, 31 Jul, 31 Oct, 31 Jan.
  US   Individual return (Form 1040): 15 April.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

from fastapi import HTTPException

MAX_DAYS = 366

WEEKEND_RULES = {
    "UK": "HMRC payments must reach HMRC by the deadline: if it falls on a weekend or bank holiday, "
          "pay so it clears by the last working day before.",
    "India": "Due dates do not move automatically; check gst.gov.in / incometax.gov.in for any extension notified.",
    "US": "The IRS treats a deadline on a weekend or legal holiday as met on the next business day.",
}


@dataclass(frozen=True)
class Rule:
    id: str
    jurisdiction: str
    title: str
    category: str
    assumes: str
    source: str
    dates: Callable[[int], list[date]]  # every due date whose year is the given year


def _monthly(day: int, march_override: tuple[int, int] | None = None) -> Callable[[int], list[date]]:
    """Due on `day` of the month after each month; optionally a different
    (month, day) for March's obligation."""
    def dates(year: int) -> list[date]:
        out = []
        for due_month in range(1, 13):
            period_month = 12 if due_month == 1 else due_month - 1
            if march_override and period_month == 3:
                continue
            out.append(date(year, due_month, min(day, calendar.monthrange(year, due_month)[1])))
        if march_override:
            out.append(date(year, *march_override))
        return sorted(out)
    return dates


def _fixed(*month_days: tuple[int, int]) -> Callable[[int], list[date]]:
    return lambda year: [date(year, m, d) for m, d in month_days]


def _uk_vat_quarters(year: int) -> list[date]:
    # Period ends 31 Mar / 30 Jun / 30 Sep / 31 Dec -> due 7 May / 7 Aug / 7 Nov / 7 Feb.
    return [date(year, 2, 7), date(year, 5, 7), date(year, 8, 7), date(year, 11, 7)]


RULES: tuple[Rule, ...] = (
    Rule("uk-vat", "UK", "VAT return and payment", "VAT",
         "Quarterly VAT periods ending at calendar quarter ends; your VAT stagger may differ.",
         "https://www.gov.uk/vat-returns/deadlines", _uk_vat_quarters),
    Rule("uk-paye", "UK", "PAYE and National Insurance payment (electronic)", "Payroll",
         "Monthly payer; tax months end on the 5th.", "https://www.gov.uk/pay-paye-tax", _monthly(22)),
    Rule("uk-sa-jan", "UK", "Self Assessment online return and balancing payment", "Income tax",
         "Individuals filing online.", "https://www.gov.uk/self-assessment-tax-returns/deadlines", _fixed((1, 31))),
    Rule("uk-sa-jul", "UK", "Self Assessment second payment on account", "Income tax",
         "Taxpayers who make payments on account.", "https://www.gov.uk/understand-self-assessment-bill/payments-on-account",
         _fixed((7, 31))),
    Rule("in-gstr1", "India", "GSTR-1 (outward supplies)", "GST",
         "Monthly filers; QRMP taxpayers file quarterly.", "https://www.gst.gov.in", _monthly(11)),
    Rule("in-gstr3b", "India", "GSTR-3B return and GST payment", "GST",
         "Monthly filers; QRMP taxpayers have the 22nd or 24th after the quarter, by state.",
         "https://www.gst.gov.in", _monthly(20)),
    Rule("in-tds-deposit", "India", "TDS / TCS deposit", "TDS",
         "Non-government deductors; tax deducted in March is due by 30 April.",
         "https://www.incometax.gov.in", _monthly(7, march_override=(4, 30))),
    Rule("in-tds-return", "India", "Quarterly TDS return (24Q / 26Q)", "TDS",
         "All deductors.", "https://www.incometax.gov.in", _fixed((1, 31), (5, 31), (7, 31), (10, 31))),
    Rule("in-advance-tax", "India", "Advance tax instalment", "Income tax",
         "Taxpayers whose tax liability is ₹10,000 or more; presumptive-scheme taxpayers pay once by 15 March.",
         "https://www.incometax.gov.in", _fixed((3, 15), (6, 15), (9, 15), (12, 15))),
    Rule("us-1040es", "US", "Estimated tax payment (Form 1040-ES)", "Income tax",
         "Individuals who expect to owe $1,000 or more.", "https://www.irs.gov/forms-pubs/about-form-1040-es",
         _fixed((1, 15), (4, 15), (6, 15), (9, 15))),
    Rule("us-941", "US", "Form 941 quarterly payroll return", "Payroll",
         "Employers filing Form 941.", "https://www.irs.gov/forms-pubs/about-form-941",
         _fixed((1, 31), (4, 30), (7, 31), (10, 31))),
    Rule("us-1040", "US", "Individual income tax return (Form 1040)", "Income tax",
         "Calendar-year individuals; an extension moves the filing date, not the payment date.",
         "https://www.irs.gov/filing", _fixed((4, 15))),
)
JURISDICTIONS = tuple(sorted({r.jurisdiction for r in RULES}))


def upcoming_deadlines(today: date, days: int = 90, jurisdiction: str = "") -> dict:
    if days < 1 or days > MAX_DAYS:
        raise HTTPException(status_code=422, detail=f"days must be between 1 and {MAX_DAYS}")
    if jurisdiction and jurisdiction not in JURISDICTIONS:
        raise HTTPException(status_code=422, detail=f"jurisdiction must be one of: {', '.join(JURISDICTIONS)}")
    end = today + timedelta(days=days)
    items = []
    for rule in RULES:
        if jurisdiction and rule.jurisdiction != jurisdiction:
            continue
        for year in range(today.year, end.year + 1):
            for due in rule.dates(year):
                if today <= due <= end:
                    weekend = due.weekday() >= 5
                    items.append({
                        "id": f"{rule.id}:{due.isoformat()}",
                        "rule": rule.id,
                        "jurisdiction": rule.jurisdiction,
                        "title": rule.title,
                        "category": rule.category,
                        "dueDate": due.isoformat(),
                        "daysLeft": (due - today).days,
                        "assumes": rule.assumes,
                        "source": rule.source,
                        "weekendNote": WEEKEND_RULES[rule.jurisdiction] if weekend else None,
                    })
    items.sort(key=lambda i: (i["dueDate"], i["jurisdiction"], i["title"]))
    return {
        "from": today.isoformat(), "to": end.isoformat(), "jurisdictions": list(JURISDICTIONS),
        "deadlines": items,
        "disclaimer": "General statutory deadlines, not client-specific. Check each item's source; "
                      "staggers, schemes, extensions and holidays can change a date.",
    }
