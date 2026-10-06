"""Fingerprint approved cases and detect exact leakage into runtime prompts.

This is an exact-text scan, not a claim that semantic paraphrases or provider
training data can be inspected. Evaluation files and tests are excluded.
"""
from __future__ import annotations
import hashlib
import re
from pathlib import Path


def normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def scan_contamination(cases: list[dict], runtime_root: Path) -> list[str]:
    texts = [normalise(p.read_text()) for p in runtime_root.rglob("*.py")]
    leaked = []
    for case in cases:
        # Ignore tiny generic phrases which are not distinctive gold examples.
        fingerprints = [normalise(case.get(field, "")) for field in ("question", "gold_answer")]
        if any(len(value) >= 80 and any(value in text for text in texts) for value in fingerprints):
            leaked.append(case["id"])
    return leaked


def case_fingerprint(case: dict) -> str:
    return hashlib.sha256(normalise(case.get("question", "") + " " + case.get("gold_answer", "")).encode()).hexdigest()


def runtime_config_hash(app_root: Path) -> str:
    import json
    import os
    digest = hashlib.sha256()
    for path in sorted(app_root.rglob("*.py")):
        digest.update(str(path.relative_to(app_root)).encode())
        digest.update(path.read_bytes())
    # Secrets, database URLs and port numbers are deliberately excluded.
    defaults = {"EMBEDDING_PROVIDER": "local", "EMBEDDING_MODEL": "BAAI/bge-small-en-v1.5",
                "SEMANTIC_RETRIEVAL_MIN_SIMILARITY": "0.72", "CLAIM_VERIFICATION": "on"}
    fields = (*defaults, "GROQ_MODEL", "GROQ_VERIFIER_MODEL", "GROQ_FAST_ANSWER_MODEL", "GEMINI_MODEL",
              "GEMINI_CLASSIFIER_MODEL", "QUERY_CLASSIFIER_SHADOW_MODE", "GROUNDED_CONTEXT_CHAR_BUDGET",
              "FORCE_DIRECT_ANSWER")
    digest.update(str(bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))).encode())
    digest.update(str(bool(os.getenv("GROQ_API_KEY"))).encode())
    digest.update(json.dumps({field: os.getenv(field, defaults.get(field, "")) for field in fields}, sort_keys=True).encode())
    return digest.hexdigest()
