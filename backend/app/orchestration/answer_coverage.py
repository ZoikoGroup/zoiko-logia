"""Requested-topic coverage, separate from factual claim verification.

Run again after pruning: a supported remainder need not be a complete answer.
This detects omissions, not whether the remaining statements are true.
"""
import re


def requested_topic_gaps(question: str, answer: str) -> list[str]:
    gaps = []
    def has(pattern):
        return bool(re.search(pattern, answer, re.I))
    if re.search(r'\bmalaysia\b', question, re.I) and re.search(r'replac|currently.*gst', question, re.I):
        if not has(r'\bSST\b|sales\s+and\s+service\s+tax'):
            gaps.append('Malaysia: the tax system that replaced GST')
    if (re.search(r'unsupported\s+(?:business\s+)?explanations?|support\s+the\s+commentary', question, re.I)
            and not has(r'unsupported|unsubstantiated|not\s+(?:established|supported|proven)|'
                        r'cannot\s+(?:determine|infer|establish|conclude)|'
                        r'(?:do|does)\s+not\s+(?:show|establish|prove|demonstrate)')):
        gaps.append('assessment of the unsupported business explanation')
    tax_question = re.sub(
        r'\b(?:ignore|exclude|excluding|disregard|do not (?:include|calculate|consider))\s+(?:corporation\s+)?tax\b',
        '', question, flags=re.I,
    )
    if re.search(r'corporation tax', tax_question, re.I) and re.search(r'compare', tax_question, re.I):
        amounts = re.findall(r'£\s*(\d[\d,]*)', question)
        for amount in dict.fromkeys(amounts):
            digits = amount.replace(',', '')
            formatted = f'{int(digits):,}'
            # The requested scenario must occur alongside its rate, not only
            # in a restatement of the question or in a threshold footnote.
            if not any(re.search(rf'(?<!\d)(?:{re.escape(digits)}|{re.escape(formatted)})(?!\d)', line)
                       and re.search(r'\d+(?:\.\d+)?\s*%', line)
                       for line in answer.splitlines()):
                gaps.append(f'corporation-tax scenario for £{formatted}')
    if re.search(r'\bgst\b', question, re.I) and re.search(r'compulsory.registration', question, re.I):
        if not all(has(pattern) for pattern in (r'reverse.charge', r'casual.taxable', r'non.resident.taxable', r'exempt|except|notification')):
            gaps.append('compulsory-registration categories and their applicable exemptions')
    if re.search(r'\b(?:export|exports|us client|foreign client)\b', question, re.I) and re.search(r'when.*qualif|export.*conditions', question, re.I):
        conditions = [(r'supplier[^.\n]{0,90}(?:in India|located in India)', 'supplier location'),
                      (r'recipient[^.\n]{0,90}outside India', 'recipient location'),
                      (r'place of supply[^.\n]{0,90}outside India', 'place of supply'),
                      (r'convertible foreign|foreign exchange|Reserve Bank|\bRBI\b', 'permitted payment currency'),
                      (r'distinct person|same person|same legal entity', 'separate establishments condition')]
        for pattern, topic in conditions:
            if not has(pattern):
                gaps.append('export-of-services qualification: ' + topic)
    return gaps


from pydantic import BaseModel


class RequestedDeliverable(BaseModel):
    description: str
    status: str
    reason: str | None = None


DEFAULT_MANAGEMENT_REPORT_SECTIONS = (
    'Executive summary', 'Financial results and workings',
    'Key changes and interpretation', 'Risks and limitations',
    'Management questions', 'Recommended next steps',
)


def report_section_names(question: str) -> list[str]:
    anchor = re.search(r'\b(?:report|answer)\b[\s\S]{0,120}\b(?:sections|headings)\b', question, re.I)
    names = (re.findall(r'^\s*(?:\d+[.)]|[-*])\s+([^\n]{2,90})$', question[anchor.end():], re.M)
             if anchor else [])
    if names:
        return [name.strip(' *').rstrip(':') for name in names]
    if re.search(r'\breport\b', question, re.I) and re.search(r'\b(?:six|6)[\s-]+sections?\b', question, re.I):
        return list(DEFAULT_MANAGEMENT_REPORT_SECTIONS)
    return []


def check_requested_deliverables(question, answer, *, has_visual=False, calculation=None):
    """Check explicit report headings and conclusively incomplete structures.

    Semantic claims retain the existing evidence and calculation validators.
    This checker does not infer that plausible prose fulfils an arbitrary task.
    """
    checks = []
    if credit_sale_journal_requested(question):
        checks.append(validate_credit_sale_journal(answer, calculation))
    normal = lambda text: ' '.join(re.findall(r'[a-z0-9]+', text.lower()))
    names = report_section_names(question)
    if names:
        lines = answer.splitlines()
        expected = {normal(name) for name in names}
        headings = {normal(re.sub(r'^\d+[.)]\s+', '', line.strip(' #*:'))): index
                    for index, line in enumerate(lines) if line.strip()}
        boundaries = sorted(headings[name] for name in expected if name in headings)
        for name in names:
            present = normal(name) in headings
            content = ''
            if present:
                start = headings[normal(name)]
                end = next((i for i in boundaries if i > start), len(lines))
                content = '\n'.join(lines[start + 1:end]).strip()
            populated = bool(content and not re.fullmatch(r'(?:TBD|pending|not available|[.\s…-]+)[.!]?', content, re.I))
            checks.append(RequestedDeliverable(description=name, status='complete' if present else 'incomplete',
                reason=None if present else 'Requested report section is absent.'))
            if present and not populated:
                checks[-1].status = 'incomplete'
                checks[-1].reason = 'Requested report section has no substantive content.'
    # Do not treat an open Markdown table or an unfinished connective as complete.
    text = answer.rstrip()
    if re.search(r'\b(?:and|because|which|with|the|an?|to)\s*$|(?:\.\.\.|…)\s*$', text, re.I):
        checks.append(RequestedDeliverable(description='Finished response', status='incomplete', reason='The response ends mid-thought.'))
    header_columns = None
    for line in answer.splitlines():
        if not line.strip().startswith('|'):
            header_columns = None
            continue
        columns = len(line.strip().strip('|').split('|'))
        if header_columns is not None and columns != header_columns:
            checks.append(RequestedDeliverable(description='Complete table', status='incomplete', reason='A table row is truncated or has missing cells.'))
            break
        header_columns = columns
    from app.orchestration.chart_intent import allows_automatic_chart
    from app.orchestration.response_planner import detect_explicit_visual_request
    if detect_explicit_visual_request(question) and allows_automatic_chart(question):
        # Legacy validated chart fences are still supported by AnswerRenderer.
        present = has_visual or bool(re.search(r'```chart\s*\n[\s\S]+?```', answer))
        if present:
            checks.append(RequestedDeliverable(description='Requested visual', status='complete'))
        elif not re.search(r'chart[^.\n]{0,70}(?:need|cannot|could not|not available|not establish|not support)|(?:need|cannot)[^.\n]{0,70}chart', answer, re.I):
            checks.append(RequestedDeliverable(description='Requested visual', status='incomplete', reason='No renderable visual payload was returned.'))
    return checks


def credit_sale_journal_requested(question: str) -> bool:
    return bool(re.search(r"\b(?:credit sale|sale on credit|sold on credit)\b", question, re.I)
                and re.search(r"\b(?:journal|entries|double[- ]entry|record)\b", question, re.I))


def validate_credit_sale_journal(answer: str, calculation=None) -> RequestedDeliverable:
    """Validate the supplied-rate net-sale exercise, not a legal VAT position.

    Unsupported formats, missing canonical inputs and broader transaction
    types remain incomplete; a balanced table alone is not accounting proof.
    """
    from decimal import Decimal, ROUND_HALF_UP
    from app.orchestration.accounting_validation import _journal_entries
    description = "Credit-sale journal entry"
    def incomplete(reason):
        return RequestedDeliverable(description=description, status="incomplete", reason=reason)
    if (calculation is None or calculation.status != "success"
            or calculation.verification_status != "passed" or "vat_on_net" not in calculation.formula_ids):
        return incomplete("The requested journal has not been validated against the supplied transaction inputs.")
    inputs = {item.name: item for item in calculation.inputs}
    outputs = {item.name: item.value for item in calculation.outputs}
    if "amount" not in inputs or not {"vat_amount", "total_including_vat"} <= outputs.keys():
        return incomplete("Canonical net-sale, tax and receivable amounts are unavailable.")
    expected = {"receivable": outputs["total_including_vat"], "revenue": inputs["amount"].value,
                "output_tax": outputs["vat_amount"]}
    money = lambda value: Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    entries = _journal_entries(answer)
    # Accept a narrow explicit Dr/Cr line format as well as a journal table.
    plain = []
    for line in re.split(r"[;\n]", answer.replace("**", "")):
        match = re.fullmatch(r"\s*(?:[-*]\s*)?(Dr|Debit|Cr|Credit)\s+([A-Za-z][A-Za-z /()-]*?)"
                             r"\s+([£$€₹]?\s*\d[\d,]*(?:\.\d+)?)\s*[.]?\s*", line, re.I)
        if match:
            from app.orchestration.calculation_service import _amount
            value = _amount(match[3])
            debit = match[1].lower() in {"dr", "debit"}
            plain.append((match[2], value if debit else None, None if debit else value, line))
    if plain:
        entries.append(plain)
    symbols = {"£": "GBP", "$": "USD", "€": "EUR", "₹": "INR"}
    declared_codes = re.findall(r"\b(?:GBP|USD|EUR|INR|AED)\b", answer, re.I)
    if any(code.upper() != inputs["amount"].currency for code in declared_codes):
        return incomplete("The stated journal currency does not match the supplied transaction currency.")
    valid_entries = 0
    for entry in entries:
        if len(entry) != 3:
            continue
        found = {}
        for account, debit, credit, text in entry:
            if any(symbol in text and code != inputs["amount"].currency for symbol,code in symbols.items()):
                break
            if re.fullmatch(r"(?:(?:trade|accounts?) )?(?:receivables?|debtors?)(?: control)?", account.strip(), re.I):
                role, value, opposite = "receivable", debit, credit
            elif re.fullmatch(r"output (?:vat|gst|tax)(?: payable)?|(?:vat|gst) (?:payable|control)", account.strip(), re.I):
                role, value, opposite = "output_tax", credit, debit
            elif re.fullmatch(r"(?:sales(?: revenue)?|revenue)", account.strip(), re.I):
                role, value, opposite = "revenue", credit, debit
            else:
                break
            if role in found or value is None or value <= 0 or opposite not in (None, Decimal(0)):
                break
            if money(value) != money(expected[role]):
                break
            found[role] = money(value)
        else:
            if set(found) == set(expected) and found["receivable"] == found["revenue"] + found["output_tax"]:
                valid_entries += 1
    if entries and valid_entries == len(entries):
        return RequestedDeliverable(description=description, status="complete",
            reason="Debit/credit accounts, amounts, currency and balance match the supplied-rate net-sale calculation; no legal applicability is certified.")
    return incomplete("Provide and validate the receivable debit, revenue credit and output-tax credit; VAT arithmetic or account names alone do not fulfil the requested journal.")
