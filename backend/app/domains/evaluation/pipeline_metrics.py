"""Observable release metrics; source recall requires curated expectations."""
from __future__ import annotations
from urllib.parse import urlparse


def _source_matches(url: str, expected: str) -> bool:
    actual, target = urlparse(url), urlparse(expected)
    return actual.scheme == "https" and actual.netloc == target.netloc and (
        actual.path.rstrip("/") == target.path.rstrip("/")
        or actual.path.startswith(target.path.rstrip("/") + "/")
    )


def measure(case: dict, result: dict, failures: list[str]) -> dict[str, bool]:
    metrics = {}
    answer = result.get("answer") or {}
    citations = answer.get("citations") or []
    expected = case.get("expected_source_urls") or []
    if expected:
        selected = (result.get("source_bundle") or {}).get("sources") or []
        # Recall of curated expected sources among the actual selected bundle.
        metrics["retrieval"] = all(any(_source_matches(source.get("source_url") or "", url)
            for source in selected) for url in expected)
        metrics["citation"] = all(any(_source_matches(citation.get("url") or "", url)
            for citation in citations) for url in expected)
    elif case.get("expect_citations") is not None:
        metrics["citation"] = bool(citations) == bool(case["expect_citations"])
    if case.get("category") == "calculation":
        metrics["calculation"] = not failures and result.get("outcome") == "answered"
    if case.get("category") == "safety":
        metrics["safety"] = not failures
    return metrics


def aggregate(results: list[dict]) -> dict:
    metrics = {}
    for name in ("retrieval", "citation", "calculation", "safety"):
        rows = [row["metrics"][name] for row in results if name in row.get("metrics", {})]
        if rows:
            metrics[name] = {"passed": sum(rows), "total": len(rows), "rate": sum(rows) / len(rows)}
    return metrics
