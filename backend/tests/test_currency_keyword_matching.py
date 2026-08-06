from app.domains.reference_data.service import match_currency_keyword


def test_matches_full_currency_name():
    assert match_currency_keyword("What is the Treasury rate for the euro?") == "Euro Zone-Euro"


def test_matches_iso_code_not_just_full_name():
    # Live bug (2026-08-06): "What is the current US Treasury exchange rate
    # for EUR?" fell through to Frankfurter/SearXNG instead of Treasury
    # because only "euro" was a recognized keyword, not the ISO code "eur".
    assert match_currency_keyword("What is the current US Treasury exchange rate for EUR?") == "Euro Zone-Euro"


def test_matches_other_iso_codes():
    assert match_currency_keyword("current CAD rate") == "Canada-Dollar"
    assert match_currency_keyword("current JPY rate") == "Japan-Yen"


def test_short_iso_code_does_not_false_positive_inside_an_unrelated_word():
    # "isk" (Iceland-Krona) is a substring of "risk" — must not match on
    # word boundaries alone, or any risk-related question about currency
    # would be wrongly routed to Treasury's Iceland data.
    assert match_currency_keyword("What is the risk of holding foreign currency?") is None


def test_returns_none_when_no_currency_named():
    assert match_currency_keyword("What is the exchange rate?") is None
