"""Deterministic BM25 and bounded second-stage governed evidence ranking.

Only passages that already passed source rights and context filters may be
supplied here. Authority/freshness are small tie-breakers, not relevance.
"""
from __future__ import annotations
import math
from collections import Counter
from datetime import date


def bm25(query_tokens: set[str], documents: dict[str, list[str]]) -> dict[str, float]:
    if not documents:
        return {}
    frequencies = {pid: Counter(tokens) for pid, tokens in documents.items()}
    mean_length = sum(map(len, documents.values())) / len(documents) or 1
    document_frequency = Counter(token for counts in frequencies.values() for token in counts)
    scores = {}
    for pid, counts in frequencies.items():
        score = 0.0
        for token in query_tokens:
            count = counts[token]
            if not count:
                continue
            inverse = math.log(1 + (len(documents) - document_frequency[token] + 0.5) / (document_frequency[token] + 0.5))
            score += inverse * count * 2.2 / (count + 1.2 * (0.25 + 0.75 * len(documents[pid]) / mean_length))
        if score:
            scores[pid] = score
    return scores


def rerank(*, fused: dict[str, float], passages: dict, sources: dict, versions: dict,
           title_coverage: dict[str, float], as_of: date) -> list[tuple[float, object]]:
    """Rerank the bounded candidate set with explicit authority and freshness.

    The <=8% adjustment cannot promote unrelated text. Effective-date and
    supersession exclusions must already have been applied by the caller.
    """
    ranked = []
    for pid, score in fused.items():
        passage = passages[pid]
        source = sources[passage.source_version_id]
        version = versions[passage.source_version_id]
        authority = {"primary": 0.03, "internal": 0.015, "secondary": 0.0}.get(source.authority_level, 0.0)
        published = version.published_at
        if published and published.date() <= as_of:
            age = (as_of - published.date()).days
            freshness = 0.02 / (1 + age / 365)
        else:
            freshness = 0.0
        exact_source = 0.03 * title_coverage.get(passage.source_version_id, 0.0)
        ranked.append((score * (1 + authority + freshness + exact_source), passage))
    return sorted(ranked, key=lambda item: (-item[0], item[1].sequence, item[1].id))


def diversify(ordered: list[tuple[float, object]], *, top_k: int, per_version_cap: int) -> list[tuple[float, object]]:
    selected, capped, counts = [], [], {}
    for item in ordered:
        version_id = item[1].source_version_id
        if counts.get(version_id, 0) >= per_version_cap:
            capped.append(item)
            continue
        counts[version_id] = counts.get(version_id, 0) + 1
        selected.append(item)
        if len(selected) == top_k:
            break
    if len(selected) < top_k:
        selected = sorted(selected + capped[:top_k - len(selected)], key=lambda item: (-item[0], item[1].sequence, item[1].id))
    return selected
