"""Deterministic handling of requests for a professional sign-off."""
import re


CERTIFICATION_REFUSAL = (
    "I cannot certify that a tax return or set of accounts is legally compliant or provide a "
    "professional sign-off. A qualified professional must review the relevant records and "
    "jurisdiction-specific requirements. I can explain general requirements or help prepare a "
    "review checklist."
)

# Something a professional signs: a return or filing, or a set of accounts.
_SIGNED_OBJECT = re.compile(
    r"\b(?:(?:income|corporation|corporate|sales|payroll|self[- ]assessment)\s+)?"
    r"(?:tax|vat|gst|hst|itr)\s+(?:returns?|filings?|computations?)\b|"
    r"\b(?:financial\s+statements|(?:annual|statutory|year[- ]end|company)\s+accounts|tax\s+filings?)\b",
    re.I,
)
# The clause must OPEN with the instruction (after any politeness), so a
# question about certification ("Who can sign off a VAT return?", "What does
# an auditor certify?") or a negation ("Do not certify …") is not a request.
_POLITE = r"(?:(?:please|kindly|can you|could you|would you|will you|i need you to|i want you to|just)\s+)*"
_SIGN_OFF = re.compile(
    rf"^{_POLITE}(?:certify|attest|sign[- ]?off|guarantee|warrant)\b", re.I,
)
# Weaker verbs are a sign-off only when paired with a compliance judgement:
# "confirm my return is compliant", not "confirm the VAT rate for books".
_CONFIRM = re.compile(rf"^{_POLITE}(?:confirm|verify|approve|validate)\b", re.I)
_COMPLIANCE_JUDGEMENT = re.compile(
    r"\b(?:compliant|compliance|legally|lawful|correct|accurate|error[- ]free|no errors|"
    r"ready to (?:file|submit)|true and fair)\b", re.I,
)
_CLAUSE = re.compile(r"[.?!;\n]+|,\s*(?:and|so|then)\s+")


def requests_tax_certification(query: str) -> bool:
    text = query.strip().strip('“”"\' ')
    if not _SIGNED_OBJECT.search(text):
        return False
    for clause in _CLAUSE.split(text):
        clause = clause.strip(' “”"\'')
        if _SIGN_OFF.search(clause):
            return True
        if _CONFIRM.search(clause) and _COMPLIANCE_JUDGEMENT.search(clause):
            return True
    return False
