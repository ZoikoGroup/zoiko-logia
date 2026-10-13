"""A source-bound mixed research/calculation answer; no embedded tax amount."""
import re
from decimal import Decimal
from urllib.parse import urlparse


def source_grounded_headroom(question, sources, citations):
    from app.orchestration.input_requirements import uk_vat_rules_requested
    from app.orchestration.source_taxonomy import detect_jurisdictions
    if not uk_vat_rules_requested(question) or not re.search(r"\bheadroom\b", question, re.I):
        return None
    if len(detect_jurisdictions(question)) > 1:
        return None
    # Historical questions and multiple amounts require the normal reasoning path.
    if re.search(r"\b20\d{2}\b", question):
        return None
    amounts = re.findall(r"£\s*(\d[\d,]*(?:\.\d+)?)", question)
    if len(amounts) != 1:
        return None
    turnover = Decimal(amounts[0].replace(',', ''))
    for source,citation in zip(sources,citations):
        url = urlparse(source.url)
        if url.hostname != 'www.gov.uk' or url.path.rstrip('/') != '/register-for-vat' or citation.url != source.url:
            continue
        text = re.sub(r'\s+', ' ', source.snippet)
        threshold = re.search(r'last\s+12\s+months.{0,100}?£\s*([\d,]+)', text, re.I)
        if not threshold or not re.search(r'next\s+30\s+days', text, re.I):
            continue
        if not re.search(r'register within 30 days of the end of the month', text, re.I):
            continue
        if not re.search(r'register by the end of (?:that|the) 30[- ]day period', text, re.I):
            continue
        limit = Decimal(threshold.group(1).replace(',', ''))
        if limit <= 0 or turnover < 0 or turnover > limit:
            return None
        ref = f'[{citation.ref_id}]'
        return (
            f'The current UK VAT registration threshold is £{limit:,.0f} of total taxable turnover in the last 12 months. {ref}\n\n'
            'Headroom calculation — assuming the supplied taxable turnover covers the same rolling 12-month period:\n\n'
            f'Headroom = £{limit:,.0f} − £{turnover:,.0f} = £{limit-turnover:,.0f}\n\n'
            f'Register if taxable turnover in the last 12 months goes over £{limit:,.0f}; register within 30 days of the end of the month when that happens. {ref}\n\n'
            f'You must also register if you expect taxable turnover to go over £{limit:,.0f} in the next 30 days; register by the end of that 30-day period. {ref}'
        )
    return None


def source_grounded_threshold_correction(question, sources, citations):
    """Compare a quoted threshold with the live HMRC page, not older announcements."""
    from app.orchestration.source_taxonomy import detect_jurisdictions
    if (detect_jurisdictions(question) != ['UK']
            or not re.search(r'\bvat\b', question, re.I)
            or not re.search(r'\bthreshold\b', question, re.I)
            or not re.search(r'\b(?:accountant|says|told|right|correct)\b', question, re.I)
            or re.search(r'\b(?:19|20)\d{2}\b', question)):
        return None
    amounts = re.findall(r'£\s*(\d[\d,]*(?:\.\d+)?)', question)
    if len(amounts)!=1:
        return None
    quoted=Decimal(amounts[0].replace(',',''))
    for source in sources:
        url=urlparse(source.url)
        if url.hostname!='www.gov.uk' or url.path.rstrip('/')!='/register-for-vat' or source.freshness!='current':
            continue
        match=re.search(r'last\s+12\s+months.{0,100}?£\s*([\d,]+)',re.sub(r'\s+',' ',source.snippet),re.I)
        citation=next((c for c in citations if c.url==source.url),None)
        if match and citation:
            actual=Decimal(match.group(1).replace(',',''))
            if actual<=0:
                return None
            ref=f'[{citation.ref_id}]'
            comparison='matches' if actual==quoted else 'does not match'
            return (f'The current HMRC VAT registration threshold is £{actual:,.0f} of taxable turnover in the last 12 months. {ref}\n\n'
                    f'The £{quoted:,.0f} figure quoted in your question {comparison} the current HMRC threshold. {ref}\n\n'
                    f'For current registration decisions, use this directly retrieved HMRC guidance. {ref}')
    return None
