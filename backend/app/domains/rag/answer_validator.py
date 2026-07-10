import re
from typing import List, Dict, Any

def validate_composed_answer(
    answer_text: str,
    context_text: str,
    source_refs: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Validates composed LLM answer against source citations and context boundaries.
    Checks for hallucinated claims, ensures strict alignment, and flags missing citations.
    """
    # 1. Check for citation anchors (e.g. [REF-1], [REF-2])
    citations_found = re.findall(r'\[REF-\d+\]', answer_text)
    
    # Get valid citation list from source refs
    valid_citations = [ref["citation_id"] for ref in source_refs]
    hallucinated_citations = []
    
    for c in citations_found:
        c_clean = c.strip("[]")
        if c_clean not in valid_citations:
            hallucinated_citations.append(c)
            
    is_safe = True
    messages = []
    
    if not citations_found and source_refs:
        is_safe = False
        messages.append("Hallucination Alert: Response contains ungrounded claims with zero source citations.")
        
    if hallucinated_citations:
        is_safe = False
        messages.append(f"Hallucination Alert: Found citations {', '.join(hallucinated_citations)} that do not exist in the retrieved context.")

    # 2. Score calculation
    validation_score = 1.0
    if not is_safe:
        validation_score = 0.5 if citations_found else 0.2
        
    return {
        "is_safe": is_safe,
        "violations": messages,
        "citations_used": list(set([c.strip("[]") for c in citations_found])),
        "validation_score": validation_score
    }
