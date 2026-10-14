"""Multilingual scope (ZL-ENG-AGT-01 §09) — the support matrix and honest
scope limits. Translation is NOT implemented, and nothing here marks it
complete (gate G7 needs specialist sign-off per language and jurisdiction).

A question in a language the matrix does not release is not answered: Kriton
says, in plain English and in the user's language where we have the
sentence, that it answers professional questions in English only. A detected
language is never used to translate figures or source wording.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageSupport:
    language: str          # ISO 639-1
    country: str           # jurisdiction the combination covers
    topics: str
    allowed_sources: str
    reviewer_available: bool
    release_status: str    # "released" | "pilot" | "not_supported"


# Seeded with what is actually supported today. Adding a row is a product
# decision that needs expert evaluation of that language and jurisdiction.
SUPPORT_MATRIX: tuple[LanguageSupport, ...] = (
    LanguageSupport("en", "UK", "accounting, VAT, corporation tax", "governed UK sources (HMRC, FRC, legislation.gov.uk)", True, "released"),
    LanguageSupport("en", "US", "accounting, federal tax", "governed US sources (IRS, FASB, SEC)", True, "released"),
    LanguageSupport("en", "IN", "income tax, GST", "official Indian sources; ingestion pending rights approval", False, "pilot"),
)

SUPPORTED_LANGUAGES = frozenset(row.language for row in SUPPORT_MATRIX if row.release_status in ("released", "pilot"))

_SCRIPTS = (
    ("hi", r"[ऀ-ॿ]"), ("ar", r"[؀-ۿ]"), ("zh", r"[一-鿿]"),
    ("ja", r"[぀-ヿ]"), ("ko", r"[가-힯]"), ("ru", r"[Ѐ-ӿ]"),
    ("ta", r"[஀-௿]"), ("te", r"[ఀ-౿]"), ("bn", r"[ঀ-৿]"),
    ("el", r"[Ͱ-Ͽ]"), ("th", r"[฀-๿]"),
)
_STOPWORDS = {
    "en": {"the", "is", "what", "how", "and", "for", "of", "to", "in", "does", "my", "are", "a", "with", "which"},
    "es": {"el", "la", "los", "las", "qué", "que", "cómo", "como", "es", "para", "por", "del", "una", "mi", "cuál", "impuesto"},
    "fr": {"le", "la", "les", "est", "quel", "quelle", "comment", "pour", "des", "une", "du", "mon", "impôt", "quels"},
    "de": {"der", "die", "das", "ist", "wie", "was", "für", "und", "ein", "eine", "mein", "welche", "steuer", "nicht"},
    "pt": {"o", "os", "as", "qual", "como", "é", "para", "uma", "meu", "do", "da", "imposto", "não"},
    "it": {"il", "lo", "gli", "qual", "come", "è", "per", "una", "mio", "della", "imposta", "non"},
}
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

_SCOPE_SENTENCES = {
    "es": "Kriton solo responde preguntas profesionales en inglés por ahora.",
    "fr": "Kriton ne répond pour l'instant qu'aux questions professionnelles en anglais.",
    "de": "Kriton beantwortet Fachfragen derzeit nur auf Englisch.",
    "pt": "Por enquanto, o Kriton só responde a perguntas profissionais em inglês.",
    "it": "Per ora Kriton risponde solo a domande professionali in inglese.",
    "hi": "Kriton अभी केवल अंग्रेज़ी में पेशेवर प्रश्नों के उत्तर देता है।",
}


def detect_language(text: str) -> str | None:
    """A conservative guess: a code only on a clear signal, None otherwise
    (callers then keep the default). A non-Latin script that makes up most
    letters wins; otherwise a Latin-script language must have at least three
    of its common words and more than English does."""
    letters = [ch for ch in text or "" if ch.isalpha()]
    if not letters:
        return None
    for code, pattern in _SCRIPTS:
        if len(re.findall(pattern, text)) / len(letters) > 0.3:
            return code
    words = [w.lower() for w in _WORD.findall(text)]
    scores = {code: sum(w in vocab for w in words) for code, vocab in _STOPWORDS.items()}
    best = max((code for code in scores if code != "en"), key=lambda code: scores[code])
    if scores[best] >= 3 and scores[best] > scores["en"]:
        return best
    return "en" if scores["en"] else None


def scope_message(language: str) -> str:
    """The honest scope limit for an unsupported language (§09.5)."""
    english = ("Kriton currently answers professional accounting and tax questions in English only, "
               "so this question was not answered. Please ask it in English. Figures, dates and source "
               "titles can stay exactly as written.")
    local = _SCOPE_SENTENCES.get(language)
    return f"{local}\n\n{english}" if local else english
