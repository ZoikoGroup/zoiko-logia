import os
import re
from datetime import date
from typing import Dict, Any

def extract_metadata_from_file(file_path: str) -> Dict[str, Any]:
    """
    Extracts metadata keys (jurisdiction, framework, version, category, source class)
    based on filename conventions and paths to automate source library tag compilation.
    """
    filename = os.path.basename(file_path)
    base_name, _ = os.path.splitext(filename)
    
    # Baseline defaults
    meta = {
        "title": base_name.replace("-", " ").replace("_", " ").title(),
        "category": "Regulatory Guidelines",
        "source_class": "External Reference",
        "jurisdiction_scope": "Global",
        "framework_scope": "GAAP",
        "version_label": "v1.0",
        "effective_from": date.today(),
        "display_restriction": "FULL",
        "tenant_id": "GLOBAL_CONTROL",
    }
    
    # 1. Jurisdiction Rollout Extraction
    name_lower = base_name.lower()
    if "uk" in name_lower:
        meta["jurisdiction_scope"] = "UK"
    elif "us-ca" in name_lower:
        meta["jurisdiction_scope"] = "US-CA"
    elif "us" in name_lower:
        meta["jurisdiction_scope"] = "US"
    elif "ifrs" in name_lower:
        meta["jurisdiction_scope"] = "IFRS"
        meta["framework_scope"] = "IFRS"
    elif "uae" in name_lower:
        meta["jurisdiction_scope"] = "UAE"
    elif "india" in name_lower:
        meta["jurisdiction_scope"] = "India"
    elif "eu" in name_lower:
        meta["jurisdiction_scope"] = "EU"

    # 2. Version Pattern Extraction (e.g., _v2_ or _v1.4)
    ver_match = re.search(r'_v(\d+(?:\.\d+)*)', base_name, re.IGNORECASE)
    if ver_match:
        meta["version_label"] = f"v{ver_match.group(1)}"

    # 3. Domain Categorization
    if "tax" in name_lower or "hmrc" in name_lower or "irs" in name_lower:
        meta["category"] = "Tax Code & Guidance"
        meta["source_class"] = "Statutory Authority"
    elif "audit" in name_lower or "isa" in name_lower:
        meta["category"] = "Auditing Standards"
        meta["source_class"] = "Professional Guidelines"
    elif "academic" in name_lower or "syllabus" in name_lower:
        meta["category"] = "Educational Syllabus"
        meta["source_class"] = "Syllabus Content"
        meta["display_restriction"] = "FULL"
    elif "internal" in name_lower or "tenant" in name_lower:
        meta["category"] = "Internal Procedures"
        meta["source_class"] = "Proprietary Document"
        meta["display_restriction"] = "REDACTED"
        # Extract dynamic tenant id if filename is like "tenant_tenant-123_document.pdf"
        tenant_match = re.search(r'tenant_([a-zA-Z0-9\-]+)', base_name)
        if tenant_match:
            meta["tenant_id"] = tenant_match.group(1)

    return meta
