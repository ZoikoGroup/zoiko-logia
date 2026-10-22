"""Answer an explicitly fictional security premise without claiming a search."""
import re


def fictional_security_answer(query):
    text = query or ''
    if not re.search(r'\bfictional\b', text, re.I) or not re.search(r'\bshare price\b', text, re.I):
        return None
    if not re.search(r'\b(?:invented ticker|fictional company|company.{0,80}fictional)\b', text, re.I):
        return None
    if re.search(r'\b(?:gross profit|revenue|cost of|exchange rate|first|second|third)\b', text, re.I):
        return None
    return (
        'You describe the company and ticker as fictional, so they do not establish a real security '
        'for which I can provide a share price. I have not verified a listing or substituted another company.\n\n'
        'For a genuine quote, provide the ticker and exchange, or a security identifier such as an ISIN '
        'where available. The share class matters when a company has several listed securities. '
        'The returned quote should identify its currency, source, observation time and whether it is delayed '
        'or a closing price.'
    )
