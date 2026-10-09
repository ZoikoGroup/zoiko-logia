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
    if re.search(r'corporation tax', question, re.I) and re.search(r'compare', question, re.I):
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
