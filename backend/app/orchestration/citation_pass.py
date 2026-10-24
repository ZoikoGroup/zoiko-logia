"""Cite the sources an answer was written from when it cites none.

"What is the difference between tax and income tax?" retrieved five OECD
sources ("Tax on personal income", "Fundamental Reform of Personal Income
Tax", …) and was answered from them without a single [REF-n] marker, so the
reader saw no sources: cited_only() lists only what the text cites, which
keeps unrelated hits out of the list.

One extra model call adds markers to the existing text; it may not change a
word of it. Each marker is then kept only when its sentence shares enough
content words with that source's text, so a marker on an unrelated source is
dropped rather than shown.
"""
from __future__ import annotations

import re
from typing import Awaitable, Callable

_MARKER = re.compile(r"\s*\[REF-(\d+)\]")
_WORD = re.compile(r"[a-z]{4,}")
_STOP = frozenset((
    "that", "this", "with", "from", "they", "their", "there", "which", "these", "those", "also", "such", "into",
    "than", "then", "when", "where", "what", "while", "have", "been", "being", "will", "would", "could", "should",
    "each", "other", "more", "most", "some", "only", "very", "about", "over", "under", "between", "both", "same",
))
MAX_SOURCES = 6
SOURCE_CHARS = 1200
MIN_SHARED_WORDS = 3

_PROMPT = (
    "Below are numbered sources and an answer written from them. Return the answer EXACTLY as written — "
    "every word, number, line break and table unchanged — except: after a sentence or table row that one of the "
    "sources directly states or supports, add its marker, for example [REF-2]. Mark only what a source supports; "
    "leave the rest unmarked. If no source supports any sentence, return the answer unchanged. Reply with the "
    "answer only.\n\n=== Sources ===\n{sources}\n\n=== Answer ===\n{answer}"
)


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP}


def _same_text(a: str, b: str) -> bool:
    return " ".join(_MARKER.sub("", a).split()) == " ".join(_MARKER.sub("", b).split())


def _supported_markers(text: str, snippets: dict[str, str]) -> str:
    """Drop each marker whose sentence shares too few words with its source."""
    def keep(match: re.Match, sentence: str) -> str:
        ref = f"REF-{match.group(1)}"
        shared = _words(sentence) & _words(snippets.get(ref, ""))
        return match.group(0) if len(shared) >= MIN_SHARED_WORDS else ""

    out = []
    for line in text.splitlines():
        # "…income. [REF-1] Next…" belongs to the sentence before it.
        line = re.sub(r"([.!?])((?:\s*\[REF-\d+\])+)", r"\2\1", line)
        pieces = re.split(r"(?<=[.!?])\s+", line) if not line.lstrip().startswith("|") else [line]
        rebuilt = []
        for piece in pieces:
            bare = _MARKER.sub("", piece)
            rebuilt.append(_MARKER.sub(lambda m, s=bare: keep(m, s), piece))
        out.append(" ".join(rebuilt) if len(pieces) > 1 else rebuilt[0] if rebuilt else line)
    return "\n".join(out)


async def cite_sources(answer: str, snippets: dict[str, str], complete: Callable[[str], Awaitable[str]],
                       provider_failure: str) -> str:
    """The answer with [REF-n] markers on what the sources support, or the
    answer unchanged when it already cites, nothing could be added, or the
    model changed its wording."""
    if not answer or not snippets or _MARKER.search(answer):
        return answer
    refs = list(snippets)[:MAX_SOURCES]
    sources = "\n\n".join(f"[{ref}] {(snippets[ref] or '')[:SOURCE_CHARS]}" for ref in refs)
    try:
        reply = (await complete(_PROMPT.format(sources=sources, answer=answer))) or ""
    except Exception:  # noqa: BLE001 — no markers is the previous behaviour
        return answer
    reply = reply.strip()
    if not reply or provider_failure in reply or not _same_text(reply, answer):
        return answer
    cited = _supported_markers(reply, {ref: snippets[ref] for ref in refs})
    return cited if _MARKER.search(cited) else answer
