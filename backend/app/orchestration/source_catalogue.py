"""
Source catalogue: official data publishers by jurisdiction and topic.

source_taxonomy.py holds the hand-picked authorities for the jurisdictions the
composer offers (UK, US, EU, UAE, India). This catalogue widens that to the
team's data-source list: central banks, statistics offices, regulators and
exchanges for many more countries, plus extra bodies for the jurisdictions the
taxonomy already covers.

It only ever ADDS domains, after the taxonomy's own, and a question touches at
most a few rows of it:

  "What is Ireland's corporation tax rate?"   -> IRELAND x tax     -> revenue.ie, gov.ie
  "Brazil inflation rate"                     -> BRAZIL x economy  -> bcb.gov.br
  "South Africa repo rate"                    -> SOUTH_AFRICA x economy -> resbank.co.za, statssa.gov.za

Countries are read from the question text (the composer selector holds only
the taxonomy's jurisdictions). A country with nothing listed for a topic adds
nothing, so the search behaves exactly as it did before for that question.

Topic keys are the values of source_taxonomy's topic constants ("tax",
"economy", …); kept as plain strings so this module has no imports and the
taxonomy can import it without a cycle.
"""
from __future__ import annotations

import re

# A central bank is the authority on both rates (economy) and banking
# supervision (markets); a statistics office on economy; an exchange or a
# securities regulator on markets; a company registry on filings.
_CATALOGUE: dict[str, dict[str, tuple[str, ...]]] = {
    # ── Extra bodies for jurisdictions source_taxonomy already covers ──────
    "GLOBAL": {
        "economy": ("bis.org", "un.org", "wto.org", "unctad.org", "undp.org", "fao.org", "iea.org", "adb.org"),
        "markets": ("fsb.org", "bis.org", "world-exchanges.org"),
        "payroll": ("ilo.org",),
    },
    "UK": {
        "economy": ("dmo.gov.uk", "data.gov.uk", "trade.gov.uk", "use-land-property-data.service.gov.uk"),
        "markets": ("dmo.gov.uk",),
        "payroll": ("thepensionsregulator.gov.uk", "ppf.co.uk"),
    },
    "US": {
        "economy": (
            "census.gov", "stlouisfed.org", "fiscaldata.treasury.gov", "usaspending.gov",
            "fhfa.gov", "eia.gov", "trade.gov", "huduser.gov", "usda.gov",
        ),
        "markets": ("cftc.gov", "fdic.gov", "consumerfinance.gov", "ofac.treasury.gov"),
    },
    "EU": {
        "economy": (
            "eib.org", "esm.europa.eu", "esrb.europa.eu", "efta.int", "eea.europa.eu", "ted.europa.eu",
        ),
        "markets": ("eba.europa.eu", "eiopa.europa.eu"),
        "tax": ("taxation-customs.ec.europa.eu", "eur-lex.europa.eu"),
        "accounting": ("eur-lex.europa.eu",),
    },
    "INDIA": {
        "economy": ("data.gov.in",),
    },
    # ── Europe ──────────────────────────────────────────────────────────────
    "IRELAND": {
        "tax": ("revenue.ie", "gov.ie"),
        "payroll": ("revenue.ie", "gov.ie"),
        "economy": (
            "cso.ie", "centralbank.ie", "ntma.ie", "gov.ie", "enterprise.gov.ie",
            "seai.ie", "propertypriceregister.ie",
        ),
        "markets": ("centralbank.ie", "cro.ie"),
        "accounting": ("cro.ie",),
    },
    # ── Americas ────────────────────────────────────────────────────────────
    "CANADA": {
        "economy": ("bankofcanada.ca", "statcan.gc.ca"),
        "markets": ("bankofcanada.ca", "ic.gc.ca"),
    },
    "BRAZIL": {"economy": ("bcb.gov.br",), "markets": ("bcb.gov.br", "b3.com.br")},
    "MEXICO": {"economy": ("banxico.org.mx", "inegi.org.mx"), "markets": ("banxico.org.mx", "bmv.com.mx")},
    "ARGENTINA": {"economy": ("bcra.gob.ar", "indec.gob.ar"), "markets": ("bcra.gob.ar", "byma.com.ar")},
    "CHILE": {"economy": ("bcentral.cl",), "markets": ("bcentral.cl", "bolsadesantiago.com")},
    "COLOMBIA": {"economy": ("banrep.gov.co", "dane.gov.co"), "markets": ("banrep.gov.co", "bvc.com.co")},
    "PERU": {"economy": ("bcrp.gob.pe", "inei.gob.pe"), "markets": ("bcrp.gob.pe", "bvl.com.pe")},
    "URUGUAY": {"economy": ("bcu.gub.uy", "gub.uy"), "markets": ("bcu.gub.uy",)},
    "ECUADOR": {"economy": ("bce.fin.ec", "ecuadorencifras.gob.ec"), "markets": ("bce.fin.ec",)},
    "COSTA_RICA": {"economy": ("bccr.fi.cr", "inec.cr"), "markets": ("bccr.fi.cr",)},
    "PANAMA": {"economy": ("inec.gob.pa",), "markets": ("superbancos.gob.pa", "latinexbolsa.com")},
    "DOMINICAN_REPUBLIC": {"economy": ("bancentral.gov.do", "one.gob.do"), "markets": ("bancentral.gov.do",)},
    "GUATEMALA": {"economy": ("banguat.gob.gt",), "markets": ("banguat.gob.gt",)},
    "PARAGUAY": {"economy": ("bcp.gov.py",), "markets": ("bcp.gov.py",)},
    "BOLIVIA": {"economy": ("bcb.gob.bo",), "markets": ("bcb.gob.bo",)},
    "HONDURAS": {"economy": ("bch.hn",), "markets": ("bch.hn",)},
    "EL_SALVADOR": {"economy": ("bcr.gob.sv",), "markets": ("bcr.gob.sv",)},
    "NICARAGUA": {"economy": ("bcn.gob.ni",), "markets": ("bcn.gob.ni",)},
    "VENEZUELA": {"economy": ("bcv.org.ve",), "markets": ("bcv.org.ve",)},
    "LATIN_AMERICA": {"economy": ("cepal.org", "iadb.org", "caf.com", "aladi.org")},
    # ── Asia-Pacific ────────────────────────────────────────────────────────
    "JAPAN": {
        "tax": ("nta.go.jp",),
        "economy": ("boj.or.jp", "e-stat.go.jp"),
        "markets": ("fsa.go.jp", "jpx.co.jp", "edinet-fsa.go.jp", "boj.or.jp"),
        "accounting": ("edinet-fsa.go.jp", "fsa.go.jp"),
    },
    "SOUTH_KOREA": {
        "economy": ("kosis.kr",),
        "markets": ("fss.or.kr",),
        "accounting": ("fss.or.kr",),
    },
    "CHINA": {"economy": ("stats.gov.cn",), "markets": ("sse.com.cn", "cninfo.com.cn")},
    "HONG_KONG": {
        "economy": ("hkma.gov.hk", "censtatd.gov.hk", "census2021.gov.hk"),
        "markets": ("hkma.gov.hk", "hkex.com.hk"),
    },
    "SINGAPORE": {
        "economy": ("mas.gov.sg", "data.gov.sg"),
        "markets": ("mas.gov.sg", "sgx.com", "acra.gov.sg"),
        "accounting": ("acra.gov.sg",),
    },
    "AUSTRALIA": {"economy": ("abs.gov.au", "rba.gov.au"), "markets": ("rba.gov.au",)},
    "NEW_ZEALAND": {"economy": ("stats.govt.nz", "rbnz.govt.nz"), "markets": ("rbnz.govt.nz", "nzx.com")},
    # ── Middle East ─────────────────────────────────────────────────────────
    "SAUDI_ARABIA": {"economy": ("sama.gov.sa", "stats.gov.sa"), "markets": ("sama.gov.sa", "saudiexchange.sa")},
    "ISRAEL": {"economy": ("boi.org.il", "cbs.gov.il"), "markets": ("boi.org.il", "tase.co.il")},
    "EGYPT": {"economy": ("cbe.org.eg", "capmas.gov.eg"), "markets": ("cbe.org.eg", "egx.com.eg")},
    "JORDAN": {"economy": ("cbj.gov.jo", "dos.gov.jo"), "markets": ("cbj.gov.jo", "exchange.jo")},
    "KUWAIT": {"economy": ("cbk.gov.kw",), "markets": ("cbk.gov.kw", "boursakuwait.com.kw")},
    "LEBANON": {"economy": ("bdl.gov.lb",), "markets": ("bdl.gov.lb", "bse.com.lb")},
    "OMAN": {"economy": ("cbo.gov.om",), "markets": ("cbo.gov.om", "msx.om")},
    "BAHRAIN": {"economy": ("cbb.gov.bh",), "markets": ("cbb.gov.bh", "bahrainbourse.com")},
    "QATAR": {"economy": ("qcb.gov.qa", "npc.qa"), "markets": ("qcb.gov.qa", "qe.com.qa")},
    "MIDDLE_EAST": {"economy": ("gccstat.org", "amf.org.ae")},
    # ── Africa ──────────────────────────────────────────────────────────────
    "SOUTH_AFRICA": {"economy": ("resbank.co.za", "statssa.gov.za"), "markets": ("resbank.co.za", "jse.co.za")},
    "NIGERIA": {"economy": ("cbn.gov.ng", "nigerianstat.gov.ng"), "markets": ("cbn.gov.ng", "ngxgroup.com")},
    "KENYA": {"economy": ("centralbank.go.ke", "knbs.or.ke"), "markets": ("centralbank.go.ke", "nse.co.ke")},
    "MOROCCO": {"economy": ("bkam.ma", "hcp.ma"), "markets": ("bkam.ma", "casablanca-bourse.com")},
    "GHANA": {"economy": ("bog.gov.gh", "statsghana.gov.gh"), "markets": ("bog.gov.gh", "gse.com.gh")},
    "TANZANIA": {"economy": ("bot.go.tz", "nbs.go.tz"), "markets": ("bot.go.tz", "dse.co.tz")},
    "UGANDA": {"economy": ("bou.or.ug", "ubos.org"), "markets": ("bou.or.ug", "use.or.ug")},
    "RWANDA": {"economy": ("bnr.rw", "statistics.gov.rw"), "markets": ("bnr.rw", "rse.rw")},
    "BOTSWANA": {"economy": ("bankofbotswana.bw", "statsbots.org.bw"), "markets": ("bankofbotswana.bw", "bse.co.bw")},
    "ZAMBIA": {"economy": ("boz.zm", "zamstats.gov.zm"), "markets": ("boz.zm", "luse.co.zm")},
    "ZIMBABWE": {"economy": ("rbz.co.zw", "zimstat.co.zw"), "markets": ("rbz.co.zw", "zse.co.zw")},
    "ETHIOPIA": {"economy": ("nbe.gov.et", "ess.gov.et"), "markets": ("nbe.gov.et",)},
    "MAURITIUS": {
        "economy": ("bom.mu", "statsmauritius.govmu.org"),
        "markets": ("bom.mu", "stockexchangeofmauritius.com"),
    },
    "NAMIBIA": {"economy": ("bon.com.na", "nsa.org.na"), "markets": ("bon.com.na", "nsx.com.na")},
    "AFRICA": {
        "economy": (
            "afdb.org", "au.int", "uneca.org", "opendataforafrica.org",
            "sadc.int", "eac.int", "comesa.int", "ecowas.int", "au-afcfta.org",
        ),
    },
}

# How each catalogue-only jurisdiction is named in a question. The taxonomy's
# own jurisdictions (UK, US, EU, INDIA) are detected there and passed in.
# Matched on word boundaries, longest alias first, like source_taxonomy.
_ALIASES: dict[str, tuple[str, ...]] = {
    "IRELAND": ("republic of ireland", "ireland", "irish"),
    "CANADA": ("canada", "canadian"),
    "BRAZIL": ("brazil", "brazilian"),
    "MEXICO": ("mexico", "mexican"),
    "ARGENTINA": ("argentina", "argentine", "argentinian"),
    "CHILE": ("chile", "chilean"),
    "COLOMBIA": ("colombia", "colombian"),
    "PERU": ("peru", "peruvian"),
    "URUGUAY": ("uruguay",),
    "ECUADOR": ("ecuador",),
    "COSTA_RICA": ("costa rica",),
    "PANAMA": ("panama",),
    "DOMINICAN_REPUBLIC": ("dominican republic",),
    "GUATEMALA": ("guatemala",),
    "PARAGUAY": ("paraguay",),
    "BOLIVIA": ("bolivia",),
    "HONDURAS": ("honduras",),
    "EL_SALVADOR": ("el salvador",),
    "NICARAGUA": ("nicaragua",),
    "VENEZUELA": ("venezuela",),
    "LATIN_AMERICA": ("latin america", "latam"),
    "JAPAN": ("japan", "japanese"),
    "SOUTH_KOREA": ("south korea", "korea", "korean"),
    "CHINA": ("china", "chinese", "prc"),
    "HONG_KONG": ("hong kong",),
    "SINGAPORE": ("singapore",),
    "AUSTRALIA": ("australia", "australian"),
    "NEW_ZEALAND": ("new zealand",),
    "SAUDI_ARABIA": ("saudi arabia", "saudi", "ksa"),
    "ISRAEL": ("israel", "israeli"),
    "EGYPT": ("egypt", "egyptian"),
    "JORDAN": ("jordan",),
    "KUWAIT": ("kuwait",),
    "LEBANON": ("lebanon",),
    "OMAN": ("oman",),
    "BAHRAIN": ("bahrain",),
    "QATAR": ("qatar",),
    "MIDDLE_EAST": ("middle east", "gcc", "gulf states"),
    "SOUTH_AFRICA": ("south africa", "south african"),
    "NIGERIA": ("nigeria", "nigerian"),
    "KENYA": ("kenya", "kenyan"),
    "MOROCCO": ("morocco", "moroccan"),
    "GHANA": ("ghana",),
    "TANZANIA": ("tanzania",),
    "UGANDA": ("uganda",),
    "RWANDA": ("rwanda",),
    "BOTSWANA": ("botswana",),
    "ZAMBIA": ("zambia",),
    "ZIMBABWE": ("zimbabwe",),
    "ETHIOPIA": ("ethiopia",),
    "MAURITIUS": ("mauritius",),
    "NAMIBIA": ("namibia",),
    "AFRICA": ("africa", "african"),
}

_ALIAS_PATTERNS: dict[str, re.Pattern[str]] = {
    key: re.compile(
        "|".join(rf"\b{re.escape(a)}\b" for a in sorted(aliases, key=len, reverse=True)),
        re.IGNORECASE,
    )
    for key, aliases in _ALIASES.items()
}

# The catalogue widens the allowlist, it does not replace it: a handful of
# extra bodies per question keeps the Tavily include list and the site: bias
# focused on the countries actually asked about.
MAX_CATALOGUE_DOMAINS = 8


def detect_catalogue_jurisdictions(query: str) -> list[str]:
    """Catalogue-only jurisdictions a question names, in the order they appear."""
    if not query:
        return []
    hits = []
    for key, pattern in _ALIAS_PATTERNS.items():
        m = pattern.search(query)
        if m:
            hits.append((m.start(), key))
    return [key for _, key in sorted(hits)]


def catalogue_domains(jurisdictions: list[str], topics: set[str] | None, query: str = "") -> list[str]:
    """Extra trusted domains for this question, at most MAX_CATALOGUE_DOMAINS.

    `jurisdictions` are the taxonomy keys already resolved for the question
    (GLOBAL first). Countries named in the question are added after them. The
    GLOBAL extras apply only when a topic was detected, so an off-taxonomy
    question's allowlist is not widened with every international body.
    """
    keys = [k for k in jurisdictions if k != "GLOBAL"]
    keys += [k for k in detect_catalogue_jurisdictions(query) if k not in keys]
    if topics and "GLOBAL" in jurisdictions:
        keys.append("GLOBAL")
    wanted = topics or None
    domains: list[str] = []
    for key in keys:
        for topic, entries in _CATALOGUE.get(key, {}).items():
            if wanted is not None and topic not in wanted:
                continue
            for d in entries:
                if d not in domains:
                    domains.append(d)
    return domains[:MAX_CATALOGUE_DOMAINS]
