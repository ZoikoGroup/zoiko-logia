from typing import List, Dict, Any, Tuple

# Real gap (2026-08-06): "What is accrued revenue?" and "Explain the
# accounting cycle..." both correctly routed to the right governed source
# (Kriton Accounting Fundamentals — a real, ~15,000-char document covering
# many topics), but that single chunk alone exceeds this module's own
# budget — the old behavior DROPPED it entirely rather than truncating,
# so a genuinely relevant source produced zero context and the query
# failed as "insufficient sources" / "clarify your jurisdiction", a
# response that doesn't even make sense for a source-coverage problem.
# A partial excerpt of a relevant document is far more useful than no
# context at all, so an over-budget chunk is now truncated to whatever
# budget remains (dropped only if that leaves less than a token amount of
# useful text) instead of being discarded outright.
_MIN_USEFUL_TRUNCATED_CHARS = 200


def build_grounded_context(chunks: List[Dict[str, Any]], max_chars: int = 8000) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Assembles the retrieved, reranked text chunks into a structured context window.
    Appends strict citation markers to ensure accountability.
    """
    context_parts = []
    source_refs = []
    current_length = 0

    for idx, chunk in enumerate(chunks):
        meta = chunk["metadata"]
        doc_title = meta.get("title", "Unknown Source")
        doc_version = meta.get("version", "v1")
        doc_jurisdiction = meta.get("jurisdiction", "Global")
        doc_path = meta.get("file_path", "unknown")

        # Format citation anchor
        citation_id = f"REF-{idx+1}"
        citation_header = f"[{citation_id}] Source: {doc_title} ({doc_version}) - Jurisdiction: {doc_jurisdiction}"
        text = chunk["text"]
        chunk_content = f"{citation_header}\nContent:\n{text}\n"

        remaining = max_chars - current_length
        if len(chunk_content) > remaining:
            overhead = len(chunk_content) - len(text)
            available_for_text = remaining - overhead
            if available_for_text < _MIN_USEFUL_TRUNCATED_CHARS:
                break
            chunk_content = f"{citation_header}\nContent:\n{text[:available_for_text].rstrip()}…\n"

        context_parts.append(chunk_content)
        current_length += len(chunk_content)

        # Track for UI display
        source_refs.append({
            "citation_id": citation_id,
            "title": doc_title,
            "version": doc_version,
            "jurisdiction": doc_jurisdiction,
            "file_path": doc_path,
        })
        if current_length >= max_chars:
            break

    full_context = "\n---\n".join(context_parts)
    return full_context, source_refs
