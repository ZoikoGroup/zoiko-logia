"""Registration comparison assembled from retrieved thresholds and statute.

Amounts, state lists and mandatory categories are extracted from official
passages; unavailable or incomplete passages never produce a complete answer.
"""
import re
from urllib.parse import urlparse


def source_grounded_registration(question, sources, citations):
    from app.orchestration.source_taxonomy import detect_jurisdictions
    if ('INDIA' not in detect_jurisdictions(question) or not re.search(r'\bgst\b', question, re.I)
            or not all(re.search(pattern, question, re.I) for pattern in (r'\bservices\b', r'\bgoods\b', r'compulsory.registration'))
            or re.search(r'\b(?:calculate|chart|historical|export)\b|\b(?:19|20)\d{2}\b', question, re.I)):
        return None
    threshold = None
    statute = None
    for source in sources:
        citation = next((c for c in citations if c.url == source.url), None)
        if not citation:
            continue
        parsed = urlparse(source.url)
        text = ' '.join(source.snippet.split())
        if parsed.hostname == 'cbic-gst.gov.in' and re.search(r'/(?:01052019|01062019)-GST-An-Update\.pdf$', parsed.path):
            services = re.search(r'suppliers of services would be Rs\.?\s*([\d.]+)\s*lakhs? and Rs\.?\s*([\d.]+)\s*lakhs?\s*\(for States of ([^)]+)\)', text, re.I)
            goods = re.search(r'suppliers of goods would be Rs\.?\s*([\d.]+)\s*lakhs? and Rs\.?\s*([\d.]+)\s*lakhs?\s*\(in the States of ([^)]+)\)', text, re.I)
            exceptions = all(re.search(pattern, text, re.I) for pattern in (r'Suppliers of services.*inter State supplies', r'Suppliers of services.*e.commerce platforms'))
            if services and goods and exceptions:
                threshold = (services.groups(), goods.groups(), citation.ref_id)
        if parsed.hostname in {'www.indiacode.nic.in', 'indiacode.nic.in'} and parsed.path.endswith('/A2017-12.pdf'):
            start = re.search(r'24\.\s*Compulsory registration in certain cases', text, re.I)
            if not start or not re.search(r'23\.\s*Persons not liable for registration', text, re.I):
                continue
            section = re.split(r'25\.\s*Procedure for registration|Section 22:', text[start.end():], flags=re.I)[0]
            markers = list(re.finditer(r'\(([ivx]+a?)\)', section))
            expected = ['i','ii','iii','iv','v','vi','vii','viii','ix','x','xi','xia','xii']
            if [m.group(1) for m in markers] != expected:
                continue
            categories = []
            for i, marker in enumerate(markers):
                body = section[marker.end():markers[i+1].start() if i+1 < len(markers) else len(section)]
                body = re.split(r'\b\d+\.\s*(?:Ins\.|Subs\.|Omitted)', body)[0]
                body = re.sub(r'\b\d+\*{3}|\b\d+\[', '', body).replace(']', '').strip(' ;–—-')
                body = re.sub(r';\s*and$', '', body).rstrip(' .;–—-')
                categories.append(body)
            statute = (categories, citation.ref_id, bool(re.search(r'aggregate turnover in a financial year', text, re.I)))
    if not threshold or not statute:
        return None
    services, goods, threshold_ref = threshold
    categories, statute_ref, has_period = statute
    period_note = f'The limits refer to aggregate turnover in a financial year. [{statute_ref}]\n\n' if has_period else ''
    return (
        '**General GST registration turnover limits**\n\n' + period_note +
        f'- Services: ₹{services[0]} lakh; ₹{services[1]} lakh in {services[2]}. [{threshold_ref}]\n'
        f'- Goods: ₹{goods[0]} lakh; ₹{goods[1]} lakh in {goods[2]}. These are turnover exemptions, subject to eligibility and compulsory-registration rules. [{threshold_ref}]\n\n'
        '**Compulsory registration**\n\n'
        f'Section 24 lists the following categories. Apply the exemptions notified under Section 23; the list must not be read as overriding those exemptions. [{statute_ref}]\n\n'
        + '\n'.join(f'- {category}. [{statute_ref}]' for category in categories)
        + '\n\n**Important service-supplier exceptions**\n\n'
        f'The CBIC guidance identifies turnover exemptions for inter-state service supplies and supplies of services through e-commerce platforms. '
        f'Check the applicable turnover limit and notification conditions before treating these supplies as requiring registration irrespective of turnover. [{threshold_ref}]'
    )
