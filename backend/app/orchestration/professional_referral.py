"""
Topic-based professional referral — per the 2026-07-22 product vision doc
(memory: product-vision-kriton-tutor-not-search, item 4). When a query needs
more than general education (a hedged HIGH-risk answer, or no usable
sources at all), the response should name the *right kind* of professional
for that specific topic, not a generic "consult a professional."

Keyed by app/orchestration/retrieve.py's infer_category() categories, since
that's already the single source of truth for "what is this query about"
everywhere else in the pipeline — no second topic classifier needed.
"""
from __future__ import annotations

_REFERRALS: dict[str, str] = {
    # Tax investigation / tax questions in general -> tax advisor, with a
    # nod to legal counsel for disputes specifically (vision doc's example).
    "tax": "a qualified tax advisor — and a tax attorney if this involves a dispute or investigation",
    "tax-regulations": "a qualified tax advisor",
    "payroll-compliance": "a qualified tax advisor or payroll specialist",
    # Audit opinion -> qualified auditor.
    "audit": "a qualified, licensed auditor",
    # Financial statements / accounting standards -> chartered accountant.
    "standards": "a chartered accountant or CPA",
    # Company law / legislation -> lawyer.
    "us-legislation": "a lawyer",
    "federal-register": "a lawyer",
    # Internal firm policy -> the firm's own compliance function, not a
    # generic external professional.
    "internal-policies": "your firm's compliance officer",
}

_DEFAULT_REFERRAL = "a qualified accounting or tax professional"


def referral_for_category(category: str) -> str:
    """Returns who to name in a professional-referral message for this
    category. Always returns something usable — falls back to a generic
    accounting/tax professional for categories with no specific mapping
    (exchange-rate, economic-data, interest-rates, education-content —
    these are reference-data/education categories, not advice-shaped ones,
    but the fallback still applies if one of them somehow reaches a
    referral-triggering route)."""
    return _REFERRALS.get(category, _DEFAULT_REFERRAL)


def referral_message(category: str) -> str:
    """The actual sentence appended to a hedged/referral response."""
    return f"For questions specific to your own situation like this, please consult {referral_for_category(category)}."
