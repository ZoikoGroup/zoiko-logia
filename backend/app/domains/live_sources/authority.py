"""
The catalogue's default authority hierarchy, as executable rules.

docs/Kriton_Authoritative_Sources_Catalog.md defines six authority levels and
then states the part that actually matters:

    The hierarchy must also account for jurisdiction, effective date, entity
    type, reporting framework, and the exact query. International models and
    professional guidance must not override binding domestic implementation.

Until now that existed only as prose. Nothing computed it, so when a bundle
mixed an OECD model rule with a domestic statute, which one an answer treated
as controlling came down to retrieval order — and retrieval order is a
relevance signal, not an authority signal. A semantically excellent match to
a professional-body summary would be cited as controlling over the enacted
legislation it was summarising.

Ranks (1 strongest):
    1  enacted legislation, official regulations, binding court decisions
    2  regulator, tax authority, or accounting/auditing standard setter
    3  official company registry or government filing system
    4  official international organisation
    5  recognised professional-body guidance
    6  commercial or secondary discovery source
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Applied to a source with no recorded rank. Deliberately weak rather than
# neutral: an unranked source must never displace one whose standing is
# actually known, and a silent default of "authoritative" is how an
# unreviewed source ends up cited as controlling.
UNKNOWN_RANK = 6

# Scopes that are not a single country. A source scoped to one of these is
# still official, but it cannot outrank a domestic source on that domestic
# source's own jurisdiction — the catalogue's "international models must not
# override binding domestic implementation" rule.
_NON_DOMESTIC_SCOPES = frozenset({"INTL", "GLOBAL", ""})


@dataclass(frozen=True)
class AuthorityCandidate:
    """One source competing to be the controlling authority for a query."""
    source_id: str
    rank: int = UNKNOWN_RANK
    # The scope this source is authoritative FOR ("GB", "US", "EU", "UN",
    # "INTL"), not the subject it happens to discuss.
    jurisdiction: str = ""
    # Most recent applicable date, ISO-8601 or a bare year. Compared as a
    # string on purpose: ISO-8601 sorts correctly lexicographically, and
    # these values arrive from a dozen upstreams in inconsistent precision
    # ("2026", "2026-07", "2026-07-31"), where parsing would mean inventing
    # a day that no authority published.
    effective_date: str = ""
    payload: object = field(default=None, compare=False)


# Governed documents carry source_library.models.Source's three-value
# authority_level and a free-text source_class, not a 1-6 rank. Deriving the
# rank from what is already recorded means the hierarchy applies to the
# existing corpus immediately, with no schema change and no re-ingestion —
# which matters because until now every document defaulted to the weakest
# rank, so a document-only bundle fell back to retrieval order and the
# hierarchy never applied at all.
#
# Keys are matched case-insensitively as substrings of source_class, since
# these values are assembled by metadata_service.extract_metadata() and by
# hand in the seed scripts, and are not a closed enum.
_DOCUMENT_CLASS_RANKS: tuple[tuple[str, int], ...] = (
    ("statutory authority", 1),
    ("legislation", 1),
    ("regulator", 2),
    ("standard setter", 2),
    ("official filing", 3),
    ("registry", 3),
    ("professional guidelines", 5),
    ("syllabus", 5),
    ("proprietary document", 6),
    ("first-party request data", 6),
    # "External Reference" is deliberately absent. It is
    # metadata_service.extract_metadata()'s baseline default, so it carries
    # no information — matching on it would discard an explicit
    # authority_level someone actually set and rank the source weakest.
)

# Fallback when source_class says nothing recognised. "primary" is the
# licence gate's strongest value but is far coarser than the catalogue's
# rank 1, so it maps to 2 (regulator/standard setter) rather than claiming
# the enacted-legislation tier a document has not evidenced.
_DOCUMENT_LEVEL_RANKS = {"primary": 2, "secondary": 5, "internal": 6}


def rank_for_document(authority_level: str, source_class: str = "") -> int:
    lowered = (source_class or "").lower()
    for marker, rank in _DOCUMENT_CLASS_RANKS:
        if marker in lowered:
            return rank
    return _DOCUMENT_LEVEL_RANKS.get((authority_level or "").lower(), UNKNOWN_RANK)


def _jurisdiction_penalty(candidate: AuthorityCandidate, query_jurisdiction: str) -> int:
    """0 when this source is authoritative for the jurisdiction asked about,
    1 for a non-domestic scope, 2 for a different country's domestic source.

    A different country's law is not weak authority — it is the wrong
    authority, so it sorts below an international model that at least claims
    to apply. This runs before rank so a rank-1 foreign statute cannot
    outrank the rank-2 domestic regulator that actually governs the answer.
    """
    if not query_jurisdiction:
        return 0
    scope = (candidate.jurisdiction or "").upper()
    asked = query_jurisdiction.upper()
    if scope == asked:
        return 0
    # EU-scoped sources are domestic for EU member-state questions in the
    # sense that matters here: EU law binds within the member state. Kriton
    # has no member-state table yet, so this stays conservative and treats
    # EU as non-domestic rather than guessing membership.
    if scope in _NON_DOMESTIC_SCOPES:
        return 1
    return 2


def sort_key(candidate: AuthorityCandidate, query_jurisdiction: str = "") -> tuple:
    return (
        _jurisdiction_penalty(candidate, query_jurisdiction),
        candidate.rank,
        # Later effective date wins between equals — a superseded instrument
        # of identical standing is not the controlling one. Descending, hence
        # the inversion via a reversed comparison below.
        _invert(candidate.effective_date),
        candidate.source_id,
    )


class _Descending(str):
    """A string that sorts in reverse, so a single ascending sort key can mix
    'smaller is better' fields with 'later is better' ones."""

    def __lt__(self, other) -> bool:  # type: ignore[override]
        return str.__gt__(self, other)

    def __le__(self, other) -> bool:  # type: ignore[override]
        return str.__ge__(self, other)

    def __gt__(self, other) -> bool:  # type: ignore[override]
        return str.__lt__(self, other)

    def __ge__(self, other) -> bool:  # type: ignore[override]
        return str.__le__(self, other)


def _invert(value: str) -> _Descending:
    return _Descending(value or "")


def order_by_authority(
    candidates: list[AuthorityCandidate], *, query_jurisdiction: str = "",
) -> list[AuthorityCandidate]:
    """Strongest authority first. Stable, so equally-authoritative sources
    keep the order the caller gave them (normally relevance)."""
    return sorted(candidates, key=lambda item: sort_key(item, query_jurisdiction))


def controlling(
    candidates: list[AuthorityCandidate], *, query_jurisdiction: str = "",
) -> AuthorityCandidate | None:
    ordered = order_by_authority(candidates, query_jurisdiction=query_jurisdiction)
    return ordered[0] if ordered else None


def explain(
    winner: AuthorityCandidate, loser: AuthorityCandidate, *, query_jurisdiction: str = "",
) -> str:
    """Why one source outranks another, for the audit record. A conflict
    resolved without a stated reason is not reviewable."""
    win_penalty = _jurisdiction_penalty(winner, query_jurisdiction)
    lose_penalty = _jurisdiction_penalty(loser, query_jurisdiction)
    if win_penalty != lose_penalty:
        return (
            f"{winner.source_id} is authoritative for {query_jurisdiction or 'the query scope'} "
            f"({winner.jurisdiction or 'unscoped'}); {loser.source_id} is scoped to "
            f"{loser.jurisdiction or 'an unstated jurisdiction'}"
        )
    if winner.rank != loser.rank:
        return (
            f"{winner.source_id} sits at authority rank {winner.rank} and "
            f"{loser.source_id} at rank {loser.rank}"
        )
    if winner.effective_date != loser.effective_date:
        return (
            f"{winner.source_id} is effective {winner.effective_date or 'undated'}, "
            f"later than {loser.source_id} at {loser.effective_date or 'undated'}"
        )
    return f"{winner.source_id} and {loser.source_id} rank equally; retrieval order retained"
