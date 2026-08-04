def acceptable_jurisdiction_scopes(jurisdiction: str) -> list[str]:
    """Given a requested jurisdiction (the UI dropdown's raw value, e.g.
    "US-CA"), returns every jurisdiction_scope value a document/chunk may
    carry to be considered in-scope for it — NOT including "Global",
    which every caller already treats as universally eligible on its own.

    A state-qualified US jurisdiction is additive to federal law, not a
    replacement for it: a California user still needs federal ("US") tax
    content, plus content scoped to "CA" specifically. Without this,
    "US-CA" only ever matched a source whose jurisdiction_scope was the
    literal string "US-CA" — no source has that; state-level content is
    tagged with the bare state code ("CA") and federal content with the
    bare "US" — so selecting "US-CA" silently excluded both (confirmed
    live: 0 eligible, 27 excluded for a California tax question).

    Every other jurisdiction value (e.g. "UK", "India") matches only
    itself, unchanged from the original behavior.

    Deliberately dependency-free (no ORM/vector-store imports) — both
    app.domains.rag.retrieval (vector-search filter construction) and
    app.orchestration.retrieve (in-Python eligibility check) import this
    at module load time, and rag.retrieval in particular has heavy
    top-level imports (llama_index, embedding models) that callers
    elsewhere go out of their way to load lazily; this module must never
    become a reason to pull those in eagerly.
    """
    prefix = "US-"
    if jurisdiction.startswith(prefix) and len(jurisdiction) > len(prefix):
        state_code = jurisdiction[len(prefix):]
        return [jurisdiction, "US", state_code]
    return [jurisdiction]
