"""Country names, for recognising that a question names a country.

source_taxonomy holds the jurisdictions Kriton has official sources for
(about twenty). A country outside that list is still a country: "What is the
consumption tax rate in Japan?" was asked "Which country…?" (19 Nov 2026).
This list only answers "does the question name a country?"; it adds no
sources and changes no routing.
"""
from __future__ import annotations

import re

_COUNTRIES = (
    "afghanistan", "albania", "algeria", "andorra", "angola", "antigua and barbuda", "argentina", "armenia",
    "australia", "austria", "azerbaijan", "bahamas", "bahrain", "bangladesh", "barbados", "belarus", "belgium",
    "belize", "benin", "bhutan", "bolivia", "bosnia and herzegovina", "botswana", "brazil", "brunei", "bulgaria",
    "burkina faso", "burundi", "cabo verde", "cape verde", "cambodia", "cameroon", "canada",
    "central african republic", "chad", "chile", "china", "colombia", "comoros", "congo", "costa rica",
    "croatia", "cuba", "cyprus", "czech republic", "czechia", "denmark", "djibouti", "dominica",
    "dominican republic", "ecuador", "egypt", "el salvador", "equatorial guinea", "eritrea", "estonia",
    "eswatini", "ethiopia", "fiji", "finland", "france", "gabon", "gambia", "georgia", "germany", "ghana",
    "greece", "grenada", "guatemala", "guinea", "guinea-bissau", "guyana", "haiti", "honduras", "hong kong",
    "hungary", "iceland", "india", "indonesia", "iran", "iraq", "ireland", "israel", "italy", "ivory coast",
    "cote d'ivoire", "jamaica", "japan", "jordan", "kazakhstan", "kenya", "kiribati", "kosovo", "kuwait",
    "kyrgyzstan", "laos", "latvia", "lebanon", "lesotho", "liberia", "libya", "liechtenstein", "lithuania",
    "luxembourg", "macau", "madagascar", "malawi", "malaysia", "maldives", "mali", "malta", "marshall islands",
    "mauritania", "mauritius", "mexico", "micronesia", "moldova", "monaco", "mongolia", "montenegro", "morocco",
    "mozambique", "myanmar", "namibia", "nauru", "nepal", "netherlands", "holland", "new zealand", "nicaragua",
    "niger", "nigeria", "north korea", "north macedonia", "norway", "oman", "pakistan", "palau", "palestine",
    "panama", "papua new guinea", "paraguay", "peru", "philippines", "poland", "portugal", "qatar", "romania",
    "russia", "rwanda", "saint kitts and nevis", "saint lucia", "saint vincent and the grenadines", "samoa",
    "san marino", "sao tome and principe", "saudi arabia", "senegal", "serbia", "seychelles", "sierra leone",
    "singapore", "slovakia", "slovenia", "solomon islands", "somalia", "south africa", "south korea", "korea",
    "south sudan", "spain", "sri lanka", "sudan", "suriname", "sweden", "switzerland", "syria", "taiwan",
    "tajikistan", "tanzania", "thailand", "timor-leste", "togo", "tonga", "trinidad and tobago", "tunisia",
    "turkey", "turkiye", "turkmenistan", "tuvalu", "uganda", "ukraine", "united arab emirates", "uae",
    "united kingdom", "uk", "united states", "usa", "uruguay", "uzbekistan", "vanuatu", "vatican", "venezuela",
    "vietnam", "viet nam", "yemen", "zambia", "zimbabwe",
)
_COUNTRY = re.compile(r"\b(?:" + "|".join(re.escape(name) for name in sorted(_COUNTRIES, key=len, reverse=True))
                      + r")\b", re.I)


def names_a_country(text: str) -> bool:
    return bool(_COUNTRY.search(text or ""))
