"""Claim-marker to governed-source citation assembly."""
from __future__ import annotations

import re

from app.orchestration.schemas import SourceBundle, SourceCitation

_REF = re.compile(r"\[REF-(\d+)\]")


def assemble_citations(
    answer_text: str,
    candidates: list[SourceCitation],
    source_bundle: SourceBundle,
) -> list[SourceCitation]:
    """Expose only cited sources permitted by the final immutable bundle.

    Multiple markers can cite different excerpts of one document. The source
    panel is document-level, so expose each governed source once; inline
    markers still preserve claim-level traceability in the answer text.
    """
    referenced = {f"REF-{number}" for number in _REF.findall(answer_text)}
    eligible_ids = {source.id for source in source_bundle.sources}
    seen: set[str] = set()
    result = []
    for citation in candidates:
        if (
            citation.ref_id not in referenced
            or citation.source_id not in eligible_ids
            or source_bundle.source_display_states.get(citation.source_id, "show") == "internal_reasoning_only"
        ):
            continue
        dedup_key = citation.source_id
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        result.append(citation)
    return result
