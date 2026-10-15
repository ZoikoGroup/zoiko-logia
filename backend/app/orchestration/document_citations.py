"""Turn an answer's "Page N" references into the citation of that page.

A balance-sheet analysis extracted every figure with its page ("| Cash and
cash equivalents | 45,000 | Page 1 – Current Assets |") but no [REF-N]
marker, so the release check rejected each row as uncited and the answer
went to human review (qry-2be1a1670944). The attached document's passages
are cited by page ("balance_sheet.pdf — Page 1"), so a page the answer names
maps to exactly one citation — which the release check then verifies against
that page's text, like any other cited claim.
"""
from __future__ import annotations

import re

_PAGE_IN_TITLE = re.compile(r"—\s*Page\s+(\d+)\s*$", re.I)
_PAGE_IN_TEXT = re.compile(r"\b(?:page|p\.)\s*(\d+)\b", re.I)
_HAS_REF = re.compile(r"\[REF-\d+\]")


def cite_document_pages(answer: str, citations) -> str:
    pages: dict[str, str] = {}
    for citation in citations:
        match = _PAGE_IN_TITLE.search(getattr(citation, "title", "") or "")
        if match:
            pages.setdefault(match.group(1), citation.ref_id)
    if not pages:
        return answer
    lines = []
    for line in (answer or "").splitlines():
        if not _HAS_REF.search(line):
            refs = list(dict.fromkeys(pages[p] for p in _PAGE_IN_TEXT.findall(line) if p in pages))
            if refs:
                markers = " ".join(f"[{ref}]" for ref in refs)
                stripped = line.rstrip()
                line = f"{stripped[:-1].rstrip()} {markers} |" if stripped.endswith("|") else f"{stripped} {markers}"
        lines.append(line)
    return "\n".join(lines)
