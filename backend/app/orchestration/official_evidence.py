"""Read authoritative entry pages alongside search, never embed tax answers.

Selection is semantic and country-specific. Facts always come from fetched page
contents; an unavailable page contributes no evidence. No governed DB ingestion.
"""
from __future__ import annotations
import asyncio
import io
import httpx
import re
from datetime import datetime, timezone


def official_pages(question: str) -> list[tuple[str, str]]:
    from app.orchestration.source_taxonomy import detect_jurisdictions
    markets = set(detect_jurisdictions(question))
    pages = []
    indirect_tax = bool(re.search(r'\b(?:vat|gst|sst)\b', question, re.I))
    if indirect_tax and 'SINGAPORE' in markets:
        pages.append(('IRAS: Current GST rates', 'https://www.iras.gov.sg/taxes/goods-services-tax-(gst)/basics-of-gst/current-gst-rates'))
    if indirect_tax and 'UAE' in markets:
        pages.append(('UAE Ministry of Finance: VAT', 'https://mof.gov.ae/en/public-finance/tax/value-added-tax-vat/'))
    if indirect_tax and 'MALAYSIA' in markets:
        pages.append(('Royal Malaysian Customs: SST', 'https://mysst.customs.gov.my/faq-sales-tax/'))
    if 'UK' in markets and re.search(r'\bcorporation tax\b', question, re.I):
        pages.append(('HMRC: Corporation Tax profit thresholds', 'https://www.gov.uk/corporation-tax-rates'))
        pages.append(('HMRC: Corporation Tax rates', 'https://www.gov.uk/government/publications/rates-and-allowances-corporation-tax/rates-and-allowances-corporation-tax'))
    if 'UK' in markets and re.search(r'\bpersonal allowance\b', question, re.I):
        pages.append(('HMRC: Income Tax rates and allowances', 'https://www.gov.uk/income-tax-rates'))
    if indirect_tax and ('INDIA' in markets or re.search(r'\b(?:bangalore|bengaluru|karnataka)\b', question, re.I)):
        if re.search(r'\b(?:registration|register|threshold)\b', question, re.I):
            pages.append(('CBIC: GST registration thresholds, 2019 update', 'https://cbic-gst.gov.in/pdf/01062019-GST-An-Update.pdf'))
            if re.search(r'compulsory', question, re.I):
                pages.append(('India Code: CGST registration provisions', 'https://www.indiacode.nic.in/indiacode/bitstream/123456789/15689/1/A2017-12.pdf'))
                pages.append(('GST Council: Registration and notification exemptions', 'https://gstcouncil.gov.in/sites/default/files/e-version-gst-flyers/Registration_under_GST_Law_new.pdf'))
        if re.search(r'\b(?:export|exports|us client|foreign|overseas)\b', question, re.I):
            pages.append(('CBIC: IGST Act export definition and zero-rating', 'https://cbic-gst.gov.in/hindi/IGST-bill-e.html'))
            pages.append(('GST Council: IGST Amendment Act 2018', 'https://gstcouncil.gov.in/sites/default/files/2024-03/annexure-5-igst-amendment-act_2018_1.pdf'))
            pages.append(('CBIC: Export-of-services sectoral guidance', 'https://cbic-gst.gov.in/sectoral-faq.html'))
    return pages


async def official_sources(question: str):
    from app.orchestration.websearch import WebSource, _read_html, _html_to_text, _relevant_excerpt, _cell_text
    pages = official_pages(question)
    if not pages:
        return []
    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True, max_redirects=3,
                                 headers={'User-Agent': 'Mozilla/5.0 (compatible; KritonResearch/1.0)'}) as client:
        async def read(title, url):
            try:
                if url.endswith('.pdf'):
                    from pypdf import PdfReader
                    async with client.stream('GET', url) as response:
                        response.raise_for_status()
                        if 'pdf' not in response.headers.get('content-type', '').lower():
                            return None
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > 2_000_000:
                                return None
                    text = await asyncio.to_thread(lambda: '\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(body)).pages))
                else:
                    markup = await _read_html(client, url)
                    text = _html_to_text(markup)
                if url.endswith('/A201713.pdf') or url.endswith('/IGST-bill-e.html'):
                    normal = ' '.join(text.split())
                    definition = re.search(r'\(6\)\s*[“\"]export of services[”\"]', normal, re.I)
                    zero_rating = re.search(r'16\.\s*Zero rated supply', normal, re.I)
                    text = '\n'.join(normal[m.start():m.start()+2500] for m in (definition, zero_rating) if m)
                if url.endswith('/A2017-12.pdf'):
                    normal = ' '.join(text.split())
                    sections = list(re.finditer(r'23\.\s*Persons not liable for registration', normal, re.I))
                    if sections:
                        registration_start = sections[-1].start()
                        previous_sections = list(re.finditer(r'22\.\s*Persons liable for registration', normal[:registration_start], re.I))
                        period = None
                        if previous_sections:
                            preceding = normal[previous_sections[-1].start():registration_start]
                            period = re.search(r'aggregate turnover in a financial year[^.;]{0,120}', preceding, re.I)
                        text = normal[registration_start:registration_start+7000]
                        text = re.split(r'25\.\s*Procedure for registration', text, flags=re.I)[0]
                        if period:
                            text += '\nSection 22: ' + period.group(0)
                if 'Registration_under_GST_Law_new.pdf' in url:
                    normal = ' '.join(text.split())
                    start = re.search(r'GST law enlists certain categories', normal, re.I)
                    if start:
                        text = normal[start.start():start.start()+5000]
                if '01062019-GST-An-Update' in url:
                    # Keep the service/goods/state mapping as one contiguous
                    # passage rather than splitting the "20/10" state limits.
                    normal = ' '.join(text.split())
                    match = re.search(r'Threshold limit of aggregate turnover for exemption', normal, re.I)
                    if match:
                        text = normal[match.start():match.start()+2200]
                        text = text.split('Taxpayers may opt')[0]
                if url == 'https://mysst.customs.gov.my/faq-sales-tax/':
                    lines = text.splitlines()
                    keep = set()
                    for i, line in enumerate(lines):
                        if re.search(r'repeal|SST comes into effect', line, re.I):
                            keep.update(range(max(0, i-1), min(len(lines), i+3)))
                    text = '\n'.join(lines[i] for i in sorted(keep))
                if 'sectoral-faq.html' in url:
                    # Large FAQ tables repeat questions across columns. Rank
                    # the export-specific rows, not unrelated transitional GST.
                    lines = [_cell_text(row) for row in re.findall(r'(?is)<tr\b[^>]*>.*?</tr\s*>', markup)]
                    lines = [line for line in lines if re.search(r'export of service|export services|letter of undertaking|zero[- ]rated|zero.rating', line, re.I)]
                    lines.sort(key=lambda line: 0 if re.search(r'distinct person|place of supply|convertible foreign', line, re.I) else 1 if 'letter of undertaking' in line.lower() else 2)
                    text = '\n'.join(lines)
                focus = question
                if 'mysst.customs.gov.my' in url:
                    focus = 'GST repealed SST comes into effect September sales service tax'
                excerpt = text[:4500] if url.endswith('/IGST-bill-e.html') or url.endswith('/A2017-12.pdf') else _relevant_excerpt(text, focus, limit=4500)
                if len(excerpt) < 80:
                    return None
                return WebSource(title=title, url=url, snippet=excerpt, provider=title.split(':')[0],
                                 fetched_at=datetime.now(timezone.utc).isoformat(),
                                 freshness='guidance' if url.endswith('.pdf') else 'current')
            except Exception:
                return None
        async def bounded(page):
            try:
                return await asyncio.wait_for(read(*page), timeout=10.0 if page[1].endswith('.pdf') else 5.0)
            except asyncio.TimeoutError:
                return None
        return [source for source in await asyncio.gather(*(bounded(page) for page in pages)) if source]


def source_grounded_current_rate(question, sources, citations):
    """A single current-rate fact extracted from its authority's current page.

    No embedded tax percentage and no source-free fallback. Exclude historical,
    future, comparative and calculation questions rather than drop requested work.
    """
    from decimal import Decimal
    from urllib.parse import urlparse
    from app.orchestration.source_taxonomy import detect_jurisdictions
    markets=detect_jurisdictions(question)
    if len(markets)!=1 or not re.search(r'\b(?:gst|vat)\b',question,re.I) or not re.search(r'\brate\b',question,re.I):
        return None
    if re.search(r'\b(?:calculate|convert|compare|chart|table|registration|historical|previous|last|explain|exceptions|rules|why|how)\b|[₹£$€]',question,re.I):
        return None
    today=datetime.now(timezone.utc).date()
    years=re.findall(r'\b(?:19|20)\d{2}\b',question)
    if years and any(int(y)!=today.year for y in years):
        return None
    for source in sources:
        url=urlparse(source.url)
        if source.freshness!='current' or not source.fetched_at or not source.fetched_at.startswith(today.isoformat()):
            continue
        flat=' '.join(source.snippet.split())
        if markets==['SINGAPORE'] and url.hostname=='www.iras.gov.sg' and url.path.endswith('/current-gst-rates'):
            match=re.search(r'current GST rate in Singapore is\s*(\d+(?:\.\d+)?)\s*%',flat,re.I)
            label='IRAS lists the current Singapore GST rate'
        else:
            continue
        citation=next((c for c in citations if c.url==source.url),None)
        if match and citation and 0<=Decimal(match.group(1))<=100:
            return f'{label} as {match.group(1)}% (official page retrieved {today.isoformat()}). [{citation.ref_id}]'
    return None


def source_grounded_tax_replacement(question, sources, citations):
    """Extract a replacement-system fact from the authority's transition FAQ.

    Require explicit repeal and dated successor evidence; never infer abolition
    from a zero rate or fill in dates from model memory.
    """
    from urllib.parse import urlparse
    if not re.search(r'\bmalaysia\b', question, re.I) or not re.search(r'replac|currently.*gst', question, re.I):
        return None
    if re.search(r'\b(?:rates?|calculate|chart|compare|threshold|registration|historical)\b|\b(?:19|20)\d{2}\b', question, re.I):
        return None
    for source in sources:
        parsed = urlparse(source.url)
        if parsed.hostname != 'mysst.customs.gov.my' or parsed.path.rstrip('/') != '/faq-sales-tax':
            continue
        text = ' '.join(source.snippet.split())
        date = re.search(r'SST comes into effect from\s+(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4})', text, re.I)
        if not date or not re.search(r'GST Act 2014 is repealed', text, re.I):
            continue
        citation = next((c for c in citations if c.url == source.url), None)
        if citation:
            return (f'Malaysia no longer uses GST: Royal Malaysian Customs states that GST registration ceased when the GST Act 2014 was repealed. '
                    f'Its official FAQ identifies SST as the successor regime and states that SST came into effect from {date.group(1)}. [{citation.ref_id}]')
    return None
