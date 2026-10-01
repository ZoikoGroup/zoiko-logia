"""Deciding whether a question is about one specific country.

Each new country-only connector — Bank of England Bank Rate, GOV.UK tax, Bank
of Canada, CSO Ireland, RBA, ABS, US Treasury — answers exactly one country.
That is the whole failure mode this module exists to prevent: a confident,
correctly-formatted number from the wrong country. "US government debt"
answered with Canadian debt, or "Irish CPI" answered with UK CPI, does not
read as an error. The figures are real, from the right kind of official source,
and simply about a different economy.

uk_scope.py originally did this for the UK alone. Four more countries arrived
with the same requirement, and a per-connector country list is a real risk: a
country added to one and forgotten in another becomes a silently wrong answer.
So the decision is computed once, here, for all ten countries (the original
five plus Germany, France, Japan, India and China in the 2026 expansion).

The rule is deliberately asymmetric, and deliberately the same rule the UK
guard used. Naming the target country is affirmative. Naming a DIFFERENT
country is negative, and the negative wins — "UK and US bank rate" is refused
rather than answered with one of the two, because there is no defensible way to
pick which one the user wanted. Naming no country at all leaves the question
open, and each caller then applies its own default; every source here puts the
country on the face of what it returns, so a defaulted answer is never
mistaken for a requested one.
"""
from __future__ import annotations

import re

# The ten countries this product is built around, keyed by ISO2 (the code the
# connectors themselves use). Kept as a dict so callers pass a code and cannot
# silently invent a country that has no guard.
# Bare two-letter ISO codes are matched CASE-SENSITIVELY, written (?-i:XX)
# inside an otherwise re.I pattern. A two-letter code and an ordinary English
# word are indistinguishable once case is thrown away, and for two of these
# countries that is not hypothetical:
#
#   "us" — the pronoun. Case-insensitively, "the company told us about GDP"
#          named the United States, and "give us the France inflation figure"
#          named the US *and* France. Naming a second country is what makes a
#          question look multi-country, and the rule below is that a negative
#          country wins, so a plain single-country question was refused.
#   "au" — the French preposition for "at/in the". "l'inflation au Canada"
#          named Australia and Canada, and was likewise refused.
#
# "US"/"AU"/"UK" in capitals is the conventional spelling of these countries,
# so requiring capitals for the bare form costs no real query. The long forms
# ("United States", "Australia", "British", …) stay case-insensitive because
# they are never English words.
#
# "IN" and "CN" are deliberately absent as bare codes for a stronger version
# of the same reason — "in" is one of the commonest words in English, and "cn"
# is ambiguous — so only "India"/"Indian" and "China"/"Chinese" match. That
# behaviour is unchanged; it is restated here because the tests below pin it.
_UK = re.compile(
    r"(?<!\w)(?:(?-i:UK)|(?-i:GB)\b|U\.K\.|United Kingdom|Great Britain|Britain|British|England|Scottish|Welsh)(?!\w)",
    re.I,
)
_US = re.compile(
    r"(?<!\w)(?:(?-i:US)|U\.S\.|USA|United States|America(?:n)?|Yankee)(?!\w)",
    re.I,
)
_IE = re.compile(
    r"(?<!\w)(?:Ireland|Irish|(?-i:IE)\b|Republic of Ireland|Eire)(?!\w)",
    re.I,
)
_CA = re.compile(
    r"(?<!\w)(?:Canada|Canadian|(?-i:CA)\b)(?!\w)",
    re.I,
)
# Bare "AU" is case-sensitive for the reason given in the block comment
# above: French "au" is a very common preposition, and a case-insensitive
# match made "le taux d'inflation au Canada" name Australia as well. "Austria"
# is unaffected either way and is still reported as another (unsupported)
# country, never as Australia.
_AU = re.compile(
    r"(?<!\w)(?:Australia|Australian|(?-i:AU)\b|ASX)(?!\w)",
    re.I,
)
# The five-country 2026 expansion.
#
# This comment previously read "the bare two-letter ISO codes (IN, CN) are
# deliberately NOT patterns: 'in' is an ordinary English word and 'cn' is far too
# ambiguous". CN had in fact been added as a capitals-only `(?-i:CN)` by then,
# and IN never got one, so the note described an intention the code did not
# implement. All ten of these countries now carry their capitals-only bare ISO
# code, which is the same treatment US/AU/DE/FR/JP/CA/IE already had:
#
#   - lowercase is still refused, which is what makes "in", "au", "de", "us" safe;
#   - capitals are unambiguous and are how these codes are conventionally written.
#
# The lowercase refusal is the whole safety argument, so it is what the tests
# pin. GB is here because it is the actual ISO 3166-1 alpha-2 code for the United
# Kingdom - "UK" is a colloquial abbreviation - and a system emitting `GB` got no
# country at all before this.
_DE = re.compile(
    r"(?<!\w)(?:Germany|German|Deutschland|(?-i:DE)\b)(?!\w)",
    re.I,
)
_FR = re.compile(
    r"(?<!\w)(?:France|French|(?-i:FR)\b)(?!\w)",
    re.I,
)
_JP = re.compile(
    r"(?<!\w)(?:Japan|Japanese|(?-i:JP)\b)(?!\w)",
    re.I,
)
_IN = re.compile(
    r"(?<!\w)(?:India|Indian|(?-i:IN)\b)(?!\w)",
    re.I,
)
_CN = re.compile(
    r"(?<!\w)(?:China|Chinese|(?-i:CN)\b)(?!\w)",
    re.I,
)

_COUNTRY_PATTERNS: dict[str, re.Pattern[str]] = {
    "GB": _UK,
    "US": _US,
    "IE": _IE,
    "CA": _CA,
    "AU": _AU,
    "DE": _DE,
    "FR": _FR,
    "JP": _JP,
    "IN": _IN,
    "CN": _CN,
}

_DISPLAY = {
    "GB": "United Kingdom",
    "US": "United States",
    "IE": "Ireland",
    "CA": "Canada",
    "AU": "Australia",
    "DE": "Germany",
    "FR": "France",
    "JP": "Japan",
    "IN": "India",
    "CN": "China",
}

# Broad enough to catch the plausible collisions with these ten countries'
# financial vocabulary. It only needs to be right about the countries a user is
# likely to ask about in the same breath as "debt", "inflation" or "unemployment";
# anything it misses falls through to the caller's default, which the sources
# label with their country.
#
# This list is deliberately EXHAUSTIVE over country names, not just likely ones.
# It was originally a short list of plausible-sounding rivals, and a query naming
# any country missing from it ("New Zealand", "Luxembourg") was treated as naming
# no country at all — so is_country_scoped() returned True for every connector,
# and "What is the New Zealand inflation rate?" was answered with the Irish CPI
# and the Australian CPI, while "What is the Luxembourg policy rate?" collected
# the RBA cash rate, the UK Bank Rate, the Bank of Canada rate and the US federal
# funds rate. Real, correctly-formatted numbers for the wrong economies, from
# four different official publishers at once. A missing entry is not a missed
# optimisation here; it is a wrong answer.
#
# The false-positive direction is safe: an over-broad match only refuses, sending
# the question to the web-grounded path. That is why genuinely ambiguous words
# (Jordan, Georgia, Chad, Mali, Samoa) are included — "Michael Jordan's revenue"
# is not a question this product can resolve either, and refusing beats guessing
# an economy.
_OTHER_COUNTRIES: tuple[str, ...] = (
    # Latin America and the Caribbean
    "Mexico|Mexican|Guatemala|Guatemalan|Honduras|Honduran|El Salvador|Nicaragua|"
    "Costa Rica|Costa Rican|Panama|Panamanian|Cuba|Cuban|Haiti|Haitian|Jamaica|Jamaican|"
    "Puerto Rico|Dominican Republic|Trinidad and Tobago|Trinidad|Uruguay|Uruguayan|"
    "Paraguay|Paraguayan|Guyana|Suriname|Belize|Belizean|Bahamas|Bahamian|Barbados|Barbadian|"
    "Antigua",
    # South America
    "Brazil|Brazilian|Argentina|Argentine|Chile|Chilean|Colombia|Colombian|"
    "Peru|Peruvian|Venezuela|Bolivia|Bolivian|Ecuador|Ecuadorian",
    # Asia
    "Pakistan|Pakistani|Bangladesh|Bangladeshi|Sri Lanka|Nepal|Nepalese|"
    "Bhutan|Bhutanese|Maldives|Myanmar|Burmese|Cambodia|Cambodian|Khmer|Lao|"
    "Timor-Leste|Mongolia|Mongolian|Afghanistan|"
    "Kazakh|Kazakhstan|Uzbek|Uzbekistan|Tajik|Tajikistan|Turkmen|Turkmenistan|Kyrgyz|"
    "Iran|Iranian|Iraq|Iraqi|Syria|Syrian|Lebanon|Lebanese|Jordan|Jordanian|"
    "Palestine|Yemen|Yemeni|Oman|Kuwait|Qatar|Bahrain",
    # East and Southeast Asia
    "Korea|Korean|Singapore|Singaporean|Taiwan|Taiwanese|Thailand|Thai|"
    "Indonesia|Indonesian|Malaysia|Malaysian|Philippines|Filipino|Vietnam|Vietnamese|"
    "Hong Kong|Macau|Macao|North Korea|Brunei",
    # Europe
    "Eurozone|European Union|EU\\b|euro ?area|eurozone|euro-area|Spain|Spanish|Italy|Italian|"
    "Netherlands|Dutch|Belgium|Belgian|Portugal|Portuguese|Austria|Austrian|"
    "Switzerland|Swiss|Sweden|Swedish|Norway|Norwegian|Denmark|Danish|"
    "Finland|Finnish|Iceland|Icelandic|Poland|Polish|Czech|Czechia|Hungary|Hungarian|"
    "Greece|Greek|Turkey|Turkish|Russia|Russian|Ukraine|Ukrainian|Belarus|Belarusian|"
    "Moldova|Moldovan|Romania|Romanian|Bulgaria|Bulgarian|Croatia|Croatian|"
    "Serbia|Serbian|Slovakia|Slovak|Slovenia|Slovenian|Bosnia|Herzegovina|"
    "Montenegro|Macedonia|Kosovo|Albania|Albanian|Andorra|Monaco|San Marino|Vatican|"
    "Liechtenstein|Luxembourg|Luxembourgish|Malta|Maltese|Cyprus|Cypriot|"
    "Estonia|Estonian|Latvia|Latvian|Lithuania|Lithuanian|Georgia|Georgian|"
    "Armenia|Armenian|Azerbaijan|Azerbaijani",
    # Aggregates and world scope. These are not countries and this product does
    # not cover them, so every country-only connector must refuse them rather
    # than answer with its own economy. "euro area inflation rate" was answered
    # with AUSTRALIA's CPI: "euro area" named no country and no unsupported
    # country, so each country-only connector fell back to its own default.
    # Adding the aggregate words here is the safe direction — an over-broad match
    # only refuses, sending the question to the web-grounded path.
    "World|worldwide|Global|global|"
    "euro ?area|eurozone|euro-area|G7|G20|advanced econom|emerging market",
    # Middle East and Africa
    "Israel|Israeli|Saudi|Saudi Arabia|Saudi Arabian|UAE|Emirates|"
    "Egypt|Egyptian|Morocco|Moroccan|Tunisia|Tunisian|Algeria|Algerian|Libya|Libyan|"
    "South Africa|South African|Nigeria|Nigerian|Niger|Nigerien|Kenya|Kenyan|"
    "Ethiopia|Ethiopian|Eritrea|Eritrean|Somalia|Somali|Djibouti|Sudan|South Sudan|"
    "Ghana|Ghanaian|Ivory Coast|Cote d'Ivoire|Senegal|Senegalese|Mali|Malian|"
    "Mauritania|Mauritanian|Chad|Chadian|Cameroon|Cameroonian|Gabon|Gabonese|"
    "Congo|Angola|Angolan|Zambia|Zambian|Zimbabwe|Zimbabwean|Malawi|Malawian|"
    "Mozambique|Mozambican|Botswana|Namibia|Rwanda|Burundi|Tanzania|Tanzanian|"
    "Uganda|Ugandan|Guinea|Guinean|Guinea-Bissau|Equatorial Guinea|Papua New Guinea|"
    "Sierra Leone|Liberia|Liberian|Gambia|Gambian|Lesotho|Eswatini|Seychelles|"
    "Mauritius|Mauritian|Cape Verde|Comoros",
    # North America and Oceania
    "Greenland|Bermuda|New Zealand|New Zealand|Fiji|Fijian|Samoa|Tonga|Tongan|"
    "Tuvalu|Vanuatu|Kiribati|Nauru|Palau|Marshall Islands|Micronesia|"
    "Solomon Islands|New Caledonia|Cook Islands",
)

# The alternatives are joined with "|" after each fragment's own trailing "|"
# is stripped. Joining the raw fragments instead silently welded the last
# country of one region onto the first of the next — "Brunei" + "Eurozone"
# became one alternative that matches neither word, so a Eurozone question was
# read as naming no country at all.
_OTHER = re.compile(
    r"(?<!\w)(?:"
    + "|".join(part.strip().rstrip("|") for part in _OTHER_COUNTRIES)
    + r")(?!\w)",
    re.I,
)


def display_name(iso2: str) -> str:
    """Human-readable country name for a supported ISO2 code."""
    return _DISPLAY.get(iso2, iso2)


def names_country(query: str, iso2: str) -> bool:
    """Whether the question names this specific country."""
    pattern = _COUNTRY_PATTERNS.get(iso2)
    if pattern is None:
        return False
    return bool(pattern.search(query or ""))


def names_another_country(query: str) -> bool:
    """Whether the question names a country other than the five supported here."""
    return bool(_OTHER.search(query or ""))


def named_countries(query: str) -> list[str]:
    """Every supported country named in the query, in ISO2, in mention order.

    Used by the cross-country comparison paths, where a question naming two of
    these countries must be refused by any single-country connector rather than
    answered from whichever one happens to be first in the table.
    """
    query = query or ""
    matches: list[tuple[int, str]] = []
    for iso2, pattern in _COUNTRY_PATTERNS.items():
        found = pattern.search(query)
        if found:
            matches.append((found.start(), iso2))
    return [iso2 for _, iso2 in sorted(matches)]


def is_country_scoped(query: str, iso2: str) -> bool:
    """Whether a connector for this one country may answer this question.

    False means "do not answer". That covers two distinct cases which are both
    wrong-data risks rather than errors:
      - the question names only a different country ("Canada bank rate"
        answered with the Bank Rate), and
      - the question names two of the five supported countries ("UK and
        Germany GDP"), where answering with either would be a guess.

    True means the question names this country, or names no supported country
    at all — in which case the caller applies its own default.
    """
    if iso2 not in _COUNTRY_PATTERNS:
        return False
    query = query or ""
    named = named_countries(query)
    if len(named) > 1:
        # A genuine cross-country comparison: this connector can only ever
        # speak for one of them.
        return False
    if named:
        return named[0] == iso2
    # No supported country named. An unsupported one ("New Zealand inflation")
    # is still a refusal, because it is a definite request for a different
    # economy rather than an unscoped question.
    return not names_another_country(query)
