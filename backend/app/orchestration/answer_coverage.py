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


def check_requested_deliverables(question, answer, *, has_visual=False):
    """Check explicit report headings and conclusively incomplete structures.

    Semantic claims retain the existing evidence and calculation validators.
    This checker does not infer that plausible prose fulfils an arbitrary task.
    """
    checks = []
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
