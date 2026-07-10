from typing import List, Dict, Any, Tuple

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
        chunk_content = f"{citation_header}\nContent:\n{chunk['text']}\n"
        
        # Handle context length budgets
        if current_length + len(chunk_content) > max_chars:
            break

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

    full_context = "\n---\n".join(context_parts)
    return full_context, source_refs
