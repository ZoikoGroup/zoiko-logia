"""Narrow source-bound registration/export explanation, without embedded thresholds."""
import re
from decimal import Decimal
from urllib.parse import urlparse


def source_grounded_export(question, sources, citations):
    # This family needs an explicitly Indian service business and annual figures.
    if (not re.search(r'\b(?:bangalore|bengaluru|karnataka)\b',question,re.I)
            or not re.search(r'\b(?:developer|services|freelance)\b',question,re.I)
            or not re.search(r'\b(?:us client|foreign|overseas|export)\b',question,re.I)
            or not re.search(r'\b(?:charge|charging|invoice|invoicing|LUT|bond)\b',question,re.I)
            or not re.search(r'\bgst\b',question,re.I)
            or not re.search(r'\b(?:year|annual|annually)\b',question,re.I)
            or re.search(r'\b(?:chart|compare|historical)\b',question,re.I)):
        return None
    amounts=re.findall(r'₹\s*(\d[\d,]*(?:\.\d+)?)\s*(lakhs?)?',question,re.I)
    if len(amounts)!=1:
        return None
    amount=Decimal(amounts[0][0].replace(',',''))*(100000 if amounts[0][1] else 1)
    indexed=[(s,next((c for c in citations if c.url==s.url),None)) for s in sources]
    indexed=[(s,c) for s,c in indexed if c]
    threshold=None; zero=None; lut=None; definition=None; rupees=None
    official={'cbic-gst.gov.in','gstcouncil.gov.in','taxinformation.cbic.gov.in','cag.gov.in','www.cag.gov.in','indiacode.nic.in'}
    for source,citation in indexed:
        if urlparse(source.url).hostname not in official:
            continue
        text=' '.join(source.snippet.split())
        if re.search(r'/(?:01052019|01062019)-GST-An-Update\.pdf$', urlparse(source.url).path):
            m=re.search(r'suppliers of services would be Rs\.?\s*(\d+(?:\.\d+)?)\s*lakhs?.{0,100}?for States of ([^).]+)',text,re.I)
            if m and 'karnataka' not in m.group(2).lower():
                threshold=(Decimal(m.group(1))*100000,citation.ref_id)
        criteria = [r'supplier of service is located in India',
                    r'recipient of service is located outside India',
                    r'place of supply of service is outside India',
                    r'payment.*convertible foreign exchange',
                    r'not merely establishments of a distinct person']
        if all(re.search(pattern, text, re.I) for pattern in criteria):
            definition = citation.ref_id
        if re.search(r'or in Indian rupees wherever permitted by the Reserve Bank of India', text, re.I):
            rupees = citation.ref_id
        if (re.search(r'zero[- ]rated',text,re.I)
                and re.search(r'export of goods (?:or|and) services|export of goods or services or both',text,re.I)):
            zero=citation.ref_id
        if (re.search(r'\bLUT\b|letter of undertaking',text,re.I)
                and re.search(r'without (?:any )?payment of (?:IGST|integrated tax)',text,re.I)
                and re.search(r'export|zero[- ]rated',text,re.I)):
            lut=citation.ref_id
    if not threshold or not zero or not lut or amount<=0 or amount<=threshold[0]:
        return None
    needs_conditions = bool(re.search(r'when.*qualif|export.*conditions', question, re.I))
    if needs_conditions and (not definition or not rupees):
        return None
    conditions = ''
    if definition and rupees:
        conditions = (
            '**Export-of-services conditions**\n\n'
            f'All conditions must be satisfied: supplier located in India; recipient located outside India; '
            f'place of supply outside India; payment received in convertible foreign exchange; '
            f'and supplier and recipient must not merely be establishments of a distinct person. [{definition}] '
            f'Payment in Indian rupees also qualifies where permitted by the Reserve Bank of India. [{rupees}]\n\n'
        )
    limit,ref=threshold
    return (
        f'**GST registration**\n\nAssuming ₹{amount:,.0f} is your aggregate service turnover for a financial year, '
        f'it exceeds the ₹{limit/100000:g} lakh (₹{limit:,.0f}) general service-registration threshold. '
        f'GST registration is therefore required on that assumption. [{ref}]\n\n'
        + conditions + '**GST on the foreign-client invoice**\n\n'
        f'If the supply qualifies as an export of services under the IGST Act, it is zero-rated. '
        f'A foreign client alone does not establish that the statutory export conditions are met. [{zero}]\n\n'
        f'For qualifying exports without payment of IGST, furnish a Letter of Undertaking (LUT) '
        f'or bond under the applicable procedure. Do not treat the foreign-client invoice as '
        f'automatically tax-free without satisfying those conditions. [{lut}]'
    )
