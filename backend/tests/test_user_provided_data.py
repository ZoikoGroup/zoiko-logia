from decimal import Decimal

from app.domains.reference_data.user_provided_data import (
    compose_user_provided_results,
    extract_inline_dataset,
    extract_user_data_table,
)
from app.orchestration.presentation import build_answer_presentation
from app.orchestration.retrieve import infer_category_rule


def test_quarterly_revenue_and_margin_with_natural_wording_builds_dataset_table():
    # Live bug: "Q1 revenue $500,000 and gross margin 40%" has the word
    # "revenue" between the period marker and the number — the old pattern
    # required them adjacent (only whitespace between), so this fell through
    # to the generic category-value fallback, which misread "Gross Margin"
    # as a category name and dropped the revenue figures entirely.
    query = (
        "Q1 revenue $500,000 and gross margin 40%, "
        "Q2 revenue $520,000 and gross margin 42%, "
        "Q3 revenue $510,000 and gross margin 38%, "
        "Q4 revenue $530,000 and gross margin 41%."
    )
    table = extract_user_data_table(query)
    assert table is not None
    assert table.title == "Quarterly revenue and gross margin"
    assert table.headers == ("Period", "Revenue", "Gross margin (%)")
    assert table.rows == (
        ("Q1", Decimal("500000"), Decimal("40")),
        ("Q2", Decimal("520000"), Decimal("42")),
        ("Q3", Decimal("510000"), Decimal("38")),
        ("Q4", Decimal("530000"), Decimal("41")),
    )


def test_quarterly_revenue_and_margin_with_semicolon_separators():
    query = (
        "Visualize quarterly revenue and gross margin: "
        "Q1 revenue $500,000, margin 40%; Q2 revenue $520,000, margin 42%; "
        "Q3 revenue $510,000, margin 38%; Q4 revenue $530,000, margin 41%."
    )
    table = extract_user_data_table(query)
    assert table is not None
    assert table.title == "Quarterly revenue and gross margin"
    assert len(table.rows) == 4


def test_terse_quarterly_revenue_and_margin_still_works():
    # Guards against a regression in the already-working terse phrasing
    # while fixing the natural-wording case above.
    query = "Q1 $500,000 and 40%, Q2 $520,000 and 42%."
    table = extract_user_data_table(query)
    assert table is not None
    assert table.title == "Quarterly revenue and gross margin"
    assert table.rows == (
        ("Q1", Decimal("500000"), Decimal("40")),
        ("Q2", Decimal("520000"), Decimal("42")),
    )


def test_ten_expense_categories_are_complete_current_turn_evidence_and_chartable():
    query = (
        "Create a bar chart of expenses: Payroll $100, Rent $20, Marketing $30, "
        "Software $10, Travel $5, Insurance $8, Utilities $9, Legal $12, "
        "Training $7, Other $4."
    )
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.provenance == "user_supplied_current_turn"
    assert len(dataset.rows) == 10
    assert infer_category_rule(query) == "user-provided-data"
    answer = compose_user_provided_results(query, "REF-1")
    assert answer is not None and "Based on the figures supplied in your question." in answer
    presentation = build_answer_presentation(query, answer)
    assert presentation.charts and len(presentation.charts[0].categories) == 10


def test_twenty_transaction_values_remain_a_distribution_without_retrieval():
    query = (
        "Show a histogram of transaction values: 12, 14, 15, 17, 18, 19, 20, 21, "
        "23, 24, 25, 26, 27, 29, 31, 33, 35, 38, 41, 45."
    )
    dataset = extract_inline_dataset(query)
    assert dataset is not None and len(dataset.rows) == 20
    assert dataset.rows[0] == ("Observation 1", Decimal("12"))
    assert dataset.rows[-1] == ("Observation 20", Decimal("45"))
    assert infer_category_rule(query) == "user-provided-data"
    answer = compose_user_provided_results(query, "REF-1")
    presentation = build_answer_presentation(query, answer or "")
    assert presentation.charts
    assert presentation.charts[0].type in {"histogram", "box_plot"}


def test_three_regions_retain_all_three_measures_through_presentation():
    query = (
        "Compare regions in a chart: North: headcount 10, revenue $1000, margin 20%; "
        "South: headcount 12, revenue $1200, margin 22%; "
        "West: headcount 8, revenue $900, margin 18%."
    )
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.measures == ("Headcount", "Revenue", "Margin (%)")
    assert all(len(row) == 4 for row in dataset.rows)
    answer = compose_user_provided_results(query, "REF-1")
    assert answer is not None and "| Category | Headcount | Revenue | Margin (%) |" in answer


def test_three_regions_comma_separated_still_retain_all_three_measures():
    # Real gap (2026-08-03): comma-separated rows ("North: ...,  South: ...,
    # West: ...") used to collapse to a single "Amount" column, silently
    # dropping revenue and margin — only the semicolon-separated phrasing
    # in the sibling test above worked. The query's own intro clause
    # ("comparing headcount, revenue, and margin across regions:") also
    # contains commas and a colon, which must not be mistaken for a row
    # boundary itself.
    query = (
        "Show a chart comparing headcount, revenue, and margin across regions: "
        "North: headcount 45, revenue 900000, margin 12, "
        "South: headcount 30, revenue 600000, margin 15, "
        "West: headcount 60, revenue 1200000, margin 10."
    )
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.measures == ("Headcount", "Revenue", "Margin")
    assert dataset.rows == (
        ("North", Decimal("45"), Decimal("900000"), Decimal("12")),
        ("South", Decimal("30"), Decimal("600000"), Decimal("15")),
        ("West", Decimal("60"), Decimal("1200000"), Decimal("10")),
    )
    answer = compose_user_provided_results(query, "REF-1")
    assert answer is not None and "| Category | Headcount | Revenue | Margin |" in answer


def test_cash_bridge_narrative_produces_a_correctly_signed_waterfall_dataset():
    # Real gap (2026-08-03): "Starting cash was $500k. Operations added
    # $180k, equipment purchases reduced it by $90k, ..." fell through to
    # the generic single-measure fallback, which mangled whole clauses into
    # category labels and silently dropped "Operations added $180k"
    # outright (not preceded by one of that fallback's required anchors).
    query = (
        "Starting cash was $500k. Operations added $180k, equipment purchases reduced it by $90k, "
        "taxes reduced it by $55k, financing added $120k, and dividends reduced it by $35k. "
        "Show the movement to ending cash."
    )
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.dimensions == ("Step",)
    assert dataset.measures == ("Amount",)
    assert dataset.rows == (
        ("Starting Cash", Decimal("500000")),
        ("Operations", Decimal("180000")),
        ("Equipment Purchases", Decimal("-90000")),
        ("Taxes", Decimal("-55000")),
        ("Financing", Decimal("120000")),
        ("Dividends", Decimal("-35000")),
        ("Ending Cash", Decimal("620000")),
    )
    # The ending balance must be DERIVED (start + every movement), never a
    # separately-stated or estimated figure — verify the arithmetic itself.
    assert dataset.rows[0][1] + sum(row[1] for row in dataset.rows[1:-1]) == dataset.rows[-1][1]

    answer = compose_user_provided_results(query, "REF-1")
    assert answer is not None
    presentation = build_answer_presentation(query, answer)
    assert len(presentation.charts) == 1
    chart = presentation.charts[0]
    assert chart.type == "waterfall"
    assert chart.analytical_intent == "financial_movement"
    assert chart.series[0].values == ["500000", "180000", "-90000", "-55000", "120000", "-35000", "620000"]


def test_explicit_compatible_radar_request_keeps_explicit_priority():
    query = (
        "Compare as a radar chart: North: quality 80, speed 70, reliability 90; "
        "South: quality 75, speed 85, reliability 80; "
        "West: quality 90, speed 65, reliability 85."
    )
    answer = compose_user_provided_results(query, "REF-1")
    presentation = build_answer_presentation(query, answer or "")
    assert presentation.charts[0].type == "radar"
    assert presentation.charts[0].selection_source == "explicit_user_request"


def test_explicit_incompatible_radar_request_uses_registry_fallback():
    query = "Compare as a radar chart: North $100; South $120; West $90."
    answer = compose_user_provided_results(query, "REF-1")
    presentation = build_answer_presentation(query, answer or "")
    assert presentation.charts[0].type != "radar"


def test_external_verification_and_current_tax_requests_do_not_use_inline_bypass():
    verify = "Chart values 10, 20 and verify these against official records."
    current_tax = "Calculate using values 10 and 20 with the current tax rate."
    assert extract_inline_dataset(verify) is None
    assert extract_inline_dataset(current_tax) is None
    assert infer_category_rule(current_tax) != "user-provided-data"


def test_parenthesis_and_signed_numbers_are_parsed_with_correct_sign():
    # Real gap (2026-08-04): "January ($7,500)" (accounting-negative) and
    # "February +$4,200" / "March -$3,100" (leading sign) both failed to
    # match at all previously, since the "(" or "+"/"-" sat exactly where
    # the number pattern's own optional currency symbol was checked.
    query = "Monthly adjustments: January ($7,500), February +$4,200, March -$3,100. Chart these."
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.rows == (
        ("January", Decimal("-7500")),
        ("February", Decimal("4200")),
        ("March", Decimal("-3100")),
    )


def test_signed_variance_by_division_is_parsed_and_charted():
    query = "Profit variance by division: East +$42,000, West -$18,000, North +$9,500. Show a chart of these."
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.rows == (
        ("East", Decimal("42000")),
        ("West", Decimal("-18000")),
        ("North", Decimal("9500")),
    )
    answer = compose_user_provided_results(query, "REF-1")
    presentation = build_answer_presentation(query, answer or "")
    assert presentation.charts


def test_number_before_label_funnel_phrasing_captures_every_figure():
    # Real gap (2026-08-04): "We had 12,000 visitors, 3,400 signups, and
    # 890 customers this month" puts the number BEFORE its label (a
    # funnel/count convention) — the label-first fallback used to
    # spuriously match filler words ("We had", "and") as one-figure
    # categories, undercounting the dataset and never trying the
    # number-first pattern at all. Also guards the thousands-separator
    # comma inside "12,000" itself from being mistaken for a row boundary.
    query = "We had 12,000 visitors, 3,400 signups, and 890 customers this month. Show the customer conversion funnel."
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.rows == (
        ("Visitors", Decimal("12000")),
        ("Signups", Decimal("3400")),
        ("Customers", Decimal("890")),
    )
    answer = compose_user_provided_results(query, "REF-1")
    assert answer is not None and "$" not in answer.split("|")[2]
    presentation = build_answer_presentation(query, answer)
    assert presentation.charts


def test_ranking_request_extracts_supplied_data_instead_of_llm_composition():
    # Real gap (2026-08-04): "rank"/"ranking" was missing from the
    # data-operation trigger, so a ranking request with fully supplied
    # figures skipped the deterministic inline-dataset path entirely and
    # went to open LLM composition, which pulled in unrelated retrieved
    # content instead of just ranking the three supplied figures.
    query = "Rank product revenue: Widget $50,000, Gadget $72,000, Gizmo $31,000."
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.rows == (
        ("Widget", Decimal("50000")),
        ("Gadget", Decimal("72000")),
        ("Gizmo", Decimal("31000")),
    )
    presentation = build_answer_presentation(query, compose_user_provided_results(query, "REF-1"))
    assert presentation.charts


def test_positional_vendor_comparison_preserves_all_entities_and_measures():
    # Real gap (2026-08-04): "Compare Vendor A, Vendor B, and Vendor C on
    # quality, delivery speed, reliability, and cost efficiency: Vendor A
    # 82, 75, 91, 68; ..." has no per-number label at all — each entity's
    # values are positional against the measure list stated in the intro.
    # This shape matched nothing and fell through to open LLM composition.
    query = (
        "Compare Vendor A, Vendor B, and Vendor C on quality, delivery speed, reliability, and cost efficiency: "
        "Vendor A 82, 75, 91, 68; Vendor B 76, 88, 84, 73; Vendor C 90, 72, 86, 79."
    )
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.measures == ("Quality", "Delivery Speed", "Reliability", "Cost Efficiency")
    assert dataset.rows == (
        ("Vendor A", Decimal("82"), Decimal("75"), Decimal("91"), Decimal("68")),
        ("Vendor B", Decimal("76"), Decimal("88"), Decimal("84"), Decimal("73")),
        ("Vendor C", Decimal("90"), Decimal("72"), Decimal("86"), Decimal("79")),
    )
    answer = compose_user_provided_results(query, "REF-1")
    presentation = build_answer_presentation(query, answer or "")
    assert presentation.charts and presentation.charts[0].type == "radar"


def test_positional_multi_measure_requires_matching_value_counts_per_entity():
    # An entity whose number-list length doesn't match the measure-name
    # list must never be guessed/misaligned — return None rather than
    # silently truncating or padding a mismatched row.
    query = "Compare A, B on speed, cost: A 10, 20; B 30."
    from app.domains.reference_data.user_provided_data import _extract_positional_multi_measure
    assert _extract_positional_multi_measure(query) is None


def test_variance_column_is_formatted_as_currency_not_a_raw_number():
    # Real gap (2026-08-04): a Budget/Actual/Variance table rendered the
    # Variance column as a bare unformatted number while Budget and Actual
    # correctly showed currency, an inconsistent presentation of the same
    # supplied dataset.
    query = "Compare budget versus actual: Marketing budget $10,000 and actual $12,500; Sales budget $8,000 and actual $7,200."
    answer = compose_user_provided_results(query, "REF-1")
    assert answer is not None
    assert "$2,500" in answer or "$2500" in answer


def test_unlabeled_number_list_after_colon_is_a_distribution_regardless_of_noun():
    # Real gap (2026-08-04): _DISTRIBUTION_PREFIX only recognized a fixed
    # vocabulary ("transaction/observation/sample/data value(s)"). Natural
    # phrasing with a different plural noun before the colon ("weekly
    # active users", "order sizes", "response times in milliseconds")
    # matched nothing and fell through to open LLM composition with no
    # grounding. The fix looks at shape (everything after the last colon
    # is purely a comma-separated number list) rather than vocabulary.
    query = "Plot our weekly active users over the last 6 weeks: 1200, 1350, 1290, 1480, 1600, 1750."
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.rows[0] == ("Observation 1", Decimal("1200"))
    assert dataset.rows[-1] == ("Observation 6", Decimal("1750"))
    presentation = build_answer_presentation(query, compose_user_provided_results(query, "REF-1") or "")
    assert presentation.charts


def test_labeled_percentages_do_not_get_mistaken_for_an_unlabeled_distribution():
    # The generic colon-number-list fallback above must never fire when
    # the tail after the colon actually has labels mixed in with the
    # numbers — those letters break the "numbers only" shape requirement.
    query = "Break down our expenses by category: Salaries 45%, Rent 15%, Marketing 12%, Software 10%, Travel 8%, Other 10%."
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.rows == (
        ("Salaries", Decimal("45")),
        ("Rent", Decimal("15")),
        ("Marketing", Decimal("12")),
        ("Software", Decimal("10")),
        ("Travel", Decimal("8")),
        ("Other", Decimal("10")),
    )
    presentation = build_answer_presentation(query, compose_user_provided_results(query, "REF-1") or "")
    assert presentation.charts


def test_break_down_two_words_is_recognized_same_as_breakdown():
    # Real gap (2026-08-04): _DATA_OPERATION only matched the single token
    # "breakdown", so natural two-word phrasing ("Break down our
    # expenses...") never even reached the extraction chain.
    query = "Break down headcount by department: Engineering 42, Sales 28, Support 19."
    assert extract_inline_dataset(query) is not None


def test_non_currency_supplied_dataset_is_not_blocked_by_risk_classifier():
    # Real gap (2026-08-04): the deterministic supplied-data-visualization
    # rule in risk_classifier.py required a literal $/£/€ figure, so plain
    # counts with no currency ("headcount", "active users") fell into
    # CLASSIFICATION_UNCERTAIN and asked the user to clarify a request that
    # already fully specified its own data. Now trusts extract_inline_dataset
    # directly as an independent, stronger signal.
    from app.domains.risk_safety.risk_classifier import classify

    headcount_decision = classify(
        "Display headcount by department: Engineering 42, Sales 28, Support 19, Finance 9, HR 6.",
        source_confidence="HIGH_CONFIDENCE",
    )
    assert headcount_decision["allowed"] is True
    assert headcount_decision["route"] == "LLM"
    assert "l2-deterministic-supplied-data-visualization" in headcount_decision["rules_applied"]

    users_decision = classify(
        "Plot our weekly active users over the last 6 weeks: 1200, 1350, 1290, 1480, 1600, 1750.",
        source_confidence="HIGH_CONFIDENCE",
    )
    assert users_decision["allowed"] is True
    assert users_decision["route"] == "LLM"
    assert "l2-deterministic-supplied-data-visualization" in users_decision["rules_applied"]


def test_abbreviated_billions_and_millions_are_scaled_not_truncated():
    # Real gap (2026-08-04): "Alpha Corp $4.2B" was silently answered as
    # "$4.20" — nine orders of magnitude wrong — because the number
    # pattern stopped at the digits and discarded the "B" entirely. This
    # is a correctness bug, not a rejection: worse than refusing to
    # answer, it answers confidently with the wrong figure.
    query = "Compare annual revenue across companies: Alpha Corp $4.2B, Beta Inc $2.8B, Gamma LLC $6.1B, Delta Co $1.9B."
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.rows == (
        ("Alpha Corp", Decimal("4.2E+9")),
        ("Beta Inc", Decimal("2.8E+9")),
        ("Gamma LLC", Decimal("6.1E+9")),
        ("Delta Co", Decimal("1.9E+9")),
    )
    answer = compose_user_provided_results(query, "REF-1")
    assert answer is not None
    assert "$4,200,000,000" in answer
    assert "$4.20" not in answer


def test_abbreviated_million_suffix_and_spelled_out_form_both_scale_correctly():
    query = "Show revenue by quarter: Q1 $1.2M, Q2 $1.35M, Q3 1.5 million."
    from app.domains.reference_data.user_provided_data import _decimal
    assert _decimal("1.2M") == Decimal("1.2E+6")
    assert _decimal("1.5 million") == Decimal("1.5E+6")
    # A bare number immediately followed by an unrelated word must never
    # have that word's first letter mistaken for a magnitude suffix.
    assert _decimal("40") == Decimal("40")


def test_number_followed_by_unrelated_word_does_not_apply_a_magnitude_suffix():
    # "40 Boxes", "12 Miles" — the leading letter of an unrelated word must
    # never be mistaken for K/M/B; only a genuine standalone suffix
    # (word-bounded) should ever scale the value.
    from app.domains.reference_data.user_provided_data import _NUMBER
    import re
    pattern = re.compile(_NUMBER, re.I)
    assert pattern.search("40 Boxes").group(1).strip() == "40"
    assert pattern.search("12 Miles").group(1).strip() == "12"


def test_ratio_against_industry_benchmark_with_is_phrasing_is_extracted():
    # Real gap (2026-08-04): "Our current ratio IS 1.8 against AN INDUSTRY
    # benchmark of 2.0" matched neither the old _RATIO_BENCHMARK pattern
    # (required "of", not "is", and a bare "a benchmark") nor did it clear
    # requires_external_evidence, which misfired on "current ... benchmark"
    # appearing anywhere in the same sentence and rejected it as an
    # external-data lookup even though every figure was already supplied.
    query = "Our current ratio is 1.8 against an industry benchmark of 2.0. How does that compare?"
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.rows == (("Ratio", Decimal("1.8"), Decimal("2.0"), Decimal("-0.2")),)
    answer = compose_user_provided_results(query, "REF-1")
    assert answer is not None and "1.8" in answer and "2" in answer


def test_current_tax_rate_request_still_requires_external_evidence():
    # Guards the requires_external_evidence tightening above against a
    # regression on the case it must still catch.
    from app.domains.reference_data.user_provided_data import requires_external_evidence
    assert requires_external_evidence("Calculate using values 10 and 20 with the current tax rate.") is True


def test_accounts_receivable_aging_without_an_explicit_chart_verb_is_recognized():
    # Real gap (2026-08-04): "Accounts receivable aging: current $85,000,
    # 1-30 days $42,000, ..." has no chart/show/table/etc verb — just the
    # word "aging" — so it never cleared _DATA_OPERATION and fell through
    # to open LLM composition, which found no matching authoritative
    # source and asked the user to clarify jurisdiction.
    query = "Accounts receivable aging: current $85,000, 1-30 days $42,000, 31-60 days $18,000, 61-90 days $9,500, over 90 days $4,200."
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.rows == (
        ("Current", Decimal("85000")),
        ("1-30 Days", Decimal("42000")),
        ("31-60 Days", Decimal("18000")),
        ("61-90 Days", Decimal("9500")),
        ("Over 90 Days", Decimal("4200")),
    )
    presentation = build_answer_presentation(query, compose_user_provided_results(query, "REF-1") or "")
    assert presentation.charts


def test_versus_pairs_across_comma_separated_rows_preserve_both_measures():
    # Real gap (2026-08-04): "Fieldwork 120 versus 145, Review 40 versus
    # 38, Reporting 20 versus 27" only matched its first row (the anchor
    # required ":"/";" as a row boundary, not the plain comma this
    # phrasing uses) AND the whole extraction path was gated behind
    # requiring the literal words "budget" AND "actual" both being
    # present — this query has neither, so every row after the first
    # silently lost its second ("versus") figure to the generic
    # single-measure fallback.
    query = "Show planned versus actual hours for the audit: Fieldwork 120 versus 145, Review 40 versus 38, Reporting 20 versus 27."
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.measures == ("Planned", "Actual")
    assert dataset.rows == (
        ("Fieldwork", Decimal("120"), Decimal("145")),
        ("Review", Decimal("40"), Decimal("38")),
        ("Reporting", Decimal("20"), Decimal("27")),
    )
    answer = compose_user_provided_results(query, "REF-1")
    presentation = build_answer_presentation(query, answer or "")
    assert presentation.charts


def test_budget_actual_versus_pair_still_uses_the_specific_variance_table():
    # Guards the generalized versus-pair fallback above against a
    # regression on the specific "budget"/"actual" shape, which must keep
    # using its own dedicated title/headers/derived Variance column.
    query = "Compare budget versus actual: Marketing 10000 versus 12500, Sales 8000 versus 7200."
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.measures == ("Budget", "Actual", "Variance")


def test_period_prefixed_measures_without_a_colon_preserve_every_measure():
    # Real gap (2026-08-04): "Q1 labor $40,000 materials $25,000 overhead
    # $10,000, Q2 ..." chains several measures with only a space between
    # them (no colon after the period, no comma between measures) — the
    # existing colon-anchored multi-measure extractor never engaged, and
    # this fell through to open LLM composition.
    query = (
        "Show the cost breakdown by quarter: Q1 labor $40,000 materials $25,000 overhead $10,000, "
        "Q2 labor $42,000 materials $27,000 overhead $11,000, Q3 labor $45,000 materials $24,000 overhead $12,000."
    )
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.measures == ("Labor", "Materials", "Overhead")
    assert dataset.rows == (
        ("Q1", Decimal("40000"), Decimal("25000"), Decimal("10000")),
        ("Q2", Decimal("42000"), Decimal("27000"), Decimal("11000")),
        ("Q3", Decimal("45000"), Decimal("24000"), Decimal("12000")),
    )
    answer = compose_user_provided_results(query, "REF-1")
    # Real gap (2026-08-04): cost-category measure names like "Labor"/
    # "Materials"/"Overhead" matched none of the currency-inference words,
    # so their $-supplied figures rendered as bare unformatted numbers.
    assert answer is not None and "$40,000" in answer
    presentation = build_answer_presentation(query, answer or "")
    assert presentation.charts


def test_period_multi_measure_fallback_never_preempts_revenue_expenses_profit():
    # Guards the ordering fix above: the generic period-multi-measure
    # fallback is tried LAST, after extract_user_data_table's more
    # specific revenue/expenses/profit path, so "Q1 revenue $X and
    # expenses $Y" still gets its dedicated computed Profit column instead
    # of being read as two generic measures named "Revenue"/"Expenses".
    query = "Using this data, show profit: Q1 revenue $120,000 and expenses $90,000; Q2 revenue $135,000 and expenses $92,000."
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.measures == ("Revenue", "Expenses", "Profit")


def test_paired_tuple_observations_are_extracted_with_axis_labels_from_the_intro():
    # Real gap (2026-08-04): "Plot the relationship between marketing
    # spend and new customers: ($5,000, 120), ($8,000, 210), ..." — paired
    # (x, y) observations — matched nothing at all; every prior pattern
    # assumes one label per number, not two numbers per point.
    query = (
        "Plot the relationship between marketing spend and new customers: "
        "($5,000, 120), ($8,000, 210), ($12,000, 340), ($15,000, 390), ($20,000, 510)."
    )
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.measures == ("Marketing Spend", "New Customers")
    assert dataset.rows == (
        ("Point 1", Decimal("5000"), Decimal("120")),
        ("Point 2", Decimal("8000"), Decimal("210")),
        ("Point 3", Decimal("12000"), Decimal("340")),
        ("Point 4", Decimal("15000"), Decimal("390")),
        ("Point 5", Decimal("20000"), Decimal("510")),
    )
    answer = compose_user_provided_results(query, "REF-1")
    assert answer is not None and "$5,000" in answer
    presentation = build_answer_presentation(query, answer)
    assert presentation.charts


def test_semicolon_scatter_rows_preserve_both_measures_without_colons():
    query = (
        "Analyze the relationship between advertising spend and sales: "
        "Campaign A spend 10 sales 80; Campaign B spend 15 sales 105; "
        "Campaign C spend 20 sales 125; Campaign D spend 25 sales 160; "
        "Campaign E spend 30 sales 190."
    )
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.measures == ("Spend", "Sales")
    assert dataset.rows[0] == ("Campaign A", Decimal("10"), Decimal("80"))
    presentation = build_answer_presentation(query, compose_user_provided_results(query, "REF-1") or "")
    assert presentation.charts[0].type == "scatter"


def test_semicolon_bubble_rows_preserve_price_sales_and_size():
    query = (
        "Create a bubble chart using price, sales and market size: "
        "Alpha price 10 sales 100 size 20; Beta price 15 sales 140 size 35; "
        "Gamma price 20 sales 175 size 45; Delta price 25 sales 190 size 60; "
        "Epsilon price 30 sales 230 size 75."
    )
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.measures == ("Price", "Sales", "Size")
    assert dataset.rows[-1] == ("Epsilon", Decimal("30"), Decimal("230"), Decimal("75"))
    presentation = build_answer_presentation(query, compose_user_provided_results(query, "REF-1") or "")
    assert presentation.charts[0].type == "bubble"


def test_paired_tuple_observations_without_between_intro_use_generic_axis_labels():
    query = "Chart these paired values: (10, 20), (15, 28), (22, 41), (30, 55)."
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.measures == ("X", "Y")
    assert len(dataset.rows) == 4


def test_spelled_out_numbers_are_normalized_to_digits_before_extraction():
    # Real gap (2026-08-04): "fifteen thousand on ads, eight thousand on
    # events, and twelve thousand on content" — spelled-out numbers —
    # matched no pattern at all; every extractor assumes digits. Also
    # exposed two follow-on bugs once normalized to digits: the filler
    # preposition "on" was being swallowed into the label ("On Ads"
    # instead of "Ads"), and the final item's "content. Chart it." was
    # dropped entirely because its terminator is a period followed by a
    # NEW sentence, not the absolute end of the query string.
    query = "Here's what we spent: fifteen thousand on ads, eight thousand on events, and twelve thousand on content. Chart it."
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.rows == (
        ("Ads", Decimal("15000")),
        ("Events", Decimal("8000")),
        ("Content", Decimal("12000")),
    )
    presentation = build_answer_presentation(query, compose_user_provided_results(query, "REF-1") or "")
    assert presentation.charts


def test_a_single_spelled_out_number_word_is_never_normalized_alone():
    # A lone number-word ("the one exception", "step six") is far too
    # common in ordinary prose to safely treat as a figure — only TWO OR
    # MORE consecutive number-words (a real compound like "eighty-five" or
    # "fifteen thousand") should ever be normalized.
    from app.domains.reference_data.user_provided_data import _normalize_word_numbers
    assert _normalize_word_numbers("the one exception to this rule") == "the one exception to this rule"
    assert _normalize_word_numbers("step six of the process") == "step six of the process"


def test_multi_word_spelled_out_numbers_scale_correctly():
    from app.domains.reference_data.user_provided_data import _normalize_word_numbers
    assert _normalize_word_numbers("two hundred fifty thousand dollars") == "250000 dollars"
    assert _normalize_word_numbers("eighty-five units") == "85 units"
    assert _normalize_word_numbers("one million dollars") == "1000000 dollars"


def test_value_first_terminator_before_a_new_sentence_still_closes_the_last_item():
    # Guards the lookahead fix above against a regression: the last item
    # in a list followed by a brand-new sentence ("... 890 customers this
    # month. Show the funnel.") must still close correctly, not just when
    # the query happens to end right after the last figure.
    query = "We had 12,000 visitors, 3,400 signups, and 890 customers this month. Show the customer conversion funnel."
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.rows == (
        ("Visitors", Decimal("12000")),
        ("Signups", Decimal("3400")),
        ("Customers", Decimal("890")),
    )


def test_a_complete_named_formula_calculation_never_routes_as_user_provided_data():
    # Real gap (2026-08-05): "Calculate net profit if revenue is $250,000
    # and expenses are $180,000." is a complete, valid named-formula
    # calculation (extract_named_formula resolves it correctly) — but the
    # generic inline-dataset extractor ALSO matched it, misreading the
    # whole leading clause as a category label ("Calculate Net Profit If
    # Revenue Is" -> $250,000). infer_category_rule checked the generic
    # extractor first, so retrieval_category became "user-provided-data"
    # and service.py's calculation block (explicitly gated on
    # retrieval_category != "user-provided-data") never ran — a governed,
    # verified calculation silently downgraded to an unverified "figures
    # you supplied" table with a nonsense category label.
    query = "Calculate net profit if revenue is $250,000 and expenses are $180,000."
    assert infer_category_rule(query) is None


def test_accrual_basis_of_accounting_resolves_via_deterministic_category_rule():
    # Real gap (2026-08-05): "What is the accrual basis of accounting?"
    # has "of" between "basis" and "accounting" — the keyword list only had
    # "accrual basis accounting" (no "of"), an exact contiguous phrase that
    # doesn't match. infer_category_rule silently returned None, so
    # service.py's accounting-fundamentals content-injection block (gated
    # on retrieval_category == "accounting-fundamentals") never fired —
    # context_text stayed empty and the query fell to "insufficient
    # sources" despite a perfectly relevant governed source existing.
    assert infer_category_rule("What is the accrual basis of accounting?") == "accounting-fundamentals"
    assert infer_category_rule("What is the cash basis of accounting?") == "accounting-fundamentals"


def test_accrual_or_cash_basis_alone_returns_a_focused_chunk_not_the_whole_document():
    # Real gap (2026-08-05): _focused_text()'s cash/accrual branch required
    # BOTH "cash" and "accrual" present, so asking about only one side
    # ("What is the accrual basis of accounting?") fell to the else
    # branch's full ~15,000-char document — well over
    # build_grounded_context's 8,000-char budget, which drops an
    # over-budget chunk entirely rather than truncating it. The query then
    # answered as "insufficient sources" despite the exact right source
    # existing for it.
    from app.domains.reference_data.accounting_fundamentals import to_accounting_fundamentals_rag_chunk
    for query in (
        "What is the accrual basis of accounting?",
        "What is the cash basis of accounting?",
    ):
        chunk = to_accounting_fundamentals_rag_chunk(query)
        assert len(chunk["text"]) < 2000, query
        assert "accrual" in chunk["text"].lower()


def test_plus_minus_compact_list_phrasing_produces_a_correctly_signed_waterfall():
    # Real gap (2026-08-06): "starting balance $200,000, plus deposits
    # $80,000, minus withdrawals $45,000, minus fees $5,000" — a compact
    # list convention using a leading sign-word instead of narrative verbs
    # ("X added $Y") — matched neither _STARTING_BALANCE (required a
    # linking verb: "was"/"is"/"of"/"at") nor _POSITIVE_MOVEMENT/
    # _NEGATIVE_MOVEMENT (neither recognized sign-word-first phrasing at
    # all). Fell through to the generic category fallback, which captured
    # "Minus Withdrawals" as a literal POSITIVE-valued label — silently
    # flipping the sign of real money.
    query = "Show a waterfall chart: starting balance $200,000, plus deposits $80,000, minus withdrawals $45,000, minus fees $5,000."
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.rows == (
        ("Starting Balance", Decimal("200000")),
        ("Deposits", Decimal("80000")),
        ("Withdrawals", Decimal("-45000")),
        ("Fees", Decimal("-5000")),
        ("Ending Balance", Decimal("230000")),
    )
    answer = compose_user_provided_results(query, "REF-1")
    presentation = build_answer_presentation(query, answer or "")
    assert presentation.charts and presentation.charts[0].type == "waterfall"


def test_starting_balance_without_a_linking_verb_still_matches():
    # Guards the _STARTING_BALANCE broadening above against a regression on
    # the original, still-common "was/is/of/at" narrative phrasing.
    from app.domains.reference_data.user_provided_data import _STARTING_BALANCE
    assert _STARTING_BALANCE.search("Starting cash was $500,000.") is not None
    assert _STARTING_BALANCE.search("starting balance $200,000,") is not None


def test_accounting_cycle_query_gets_a_focused_trial_balance_excerpt():
    # Real gap (2026-08-06): "Explain the accounting cycle from transaction
    # to financial statements" matched no _focused_text branch, so — even
    # after the over-budget-chunk truncation fix — the answer came from
    # whatever happens to be FIRST in the ~15,000-char document (cash/
    # accrual basis) rather than anything about the accounting cycle,
    # since truncation has no topic awareness of its own.
    from app.domains.reference_data.accounting_fundamentals import to_accounting_fundamentals_rag_chunk
    chunk = to_accounting_fundamentals_rag_chunk("Explain the accounting cycle from transaction to financial statements.")
    assert len(chunk["text"]) < 2000
    assert "trial" in chunk["text"].lower() or "ledger" in chunk["text"].lower()


def test_bridge_with_no_starting_anchor_word_still_gets_correct_signs():
    # Live bug (2026-08-06): "Chart the profit bridge from budget to
    # actual: budgeted profit $200,000, plus higher sales $35,000, minus
    # higher costs $18,000, minus one-time write-off $12,000" has a real
    # base value but no "starting" anchor word at all — _STARTING_BALANCE
    # never matched, so the whole query fell through to the generic
    # unordered category extractor, which captured "Minus Higher Costs
    # $18,000" as a literal POSITIVE category instead of a negative
    # movement, silently flipping the sign of real money.
    query = (
        "Chart the profit bridge from budget to actual: budgeted profit $200,000, "
        "plus higher sales $35,000, minus higher costs $18,000, minus one-time write-off $12,000."
    )
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.rows == (
        ("Starting Budgeted Profit", Decimal("200000")),
        ("Higher Sales", Decimal("35000")),
        ("Higher Costs", Decimal("-18000")),
        ("One-Time Write-Off", Decimal("-12000")),
        ("Ending Budgeted Profit", Decimal("205000")),
    )


def test_year_over_year_quarter_pairs_do_not_mistake_the_year_for_the_value():
    # Live bug (2026-08-06): "Q1 2025 $95,000 vs Q1 2026 $112,000, Q2 2025
    # $102,000 vs Q2 2026 $118,500" pairs the same quarter across two
    # years, with a bare year sitting between the period token and its
    # real dollar figure. The plain single-period extractor matched the
    # YEAR itself as the row's value ("Q1" -> 2025), silently discarding
    # every real dollar figure in the query.
    query = (
        "Compare this year to last year quarterly sales: Q1 2025 $95,000 vs Q1 2026 $112,000, "
        "Q2 2025 $102,000 vs Q2 2026 $118,500."
    )
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.measures == ("2025", "2026")
    assert dataset.rows == (
        ("Q1", Decimal("95000"), Decimal("112000")),
        ("Q2", Decimal("102000"), Decimal("118500")),
    )
    assert dataset.units == ("USD", "USD")


def test_cash_header_gets_currency_formatting_not_bare_numbers():
    # Live bug (2026-08-06): "Chart our cash balance over the last 4
    # quarters" produced a table headed just "Cash" — not in the units-
    # inference keyword whitelist, so real dollar figures rendered as bare
    # unformatted numbers ("180000") instead of "$180,000".
    query = "Chart our cash balance over the last 4 quarters: Q1 $180,000, Q2 $165,000, Q3 $210,000, Q4 $195,000."
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.measures == ("Cash",)
    assert dataset.units == ("USD",)


def test_acronym_category_labels_are_preserved_not_title_cased():
    # Live bug (2026-08-06): plain str.title() mangled "APAC" -> "Apac" and
    # "LATAM" -> "Latam", silently destroying real region/entity codes
    # supplied by the user.
    query = "What's the distribution of our customer base by region: North America 4,500, Europe 2,800, APAC 1,900, LATAM 700?"
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    labels = [row[0] for row in dataset.rows]
    assert "APAC" in labels
    assert "LATAM" in labels
    assert "North America" in labels


def test_percent_suffixed_category_values_keep_their_percent_unit():
    # Live bug (2026-08-06): "Alice 34%, Bob 28%, Carla 41%, ..." lost the
    # "%" entirely — the category-value extractor's number group never
    # captures a trailing "%", so the header stayed a bare "Amount" and the
    # figures were presented as unitless counts (with a meaningless summed
    # "total" across percentages).
    query = "Which sales reps had the highest close rate — rank them: Alice 34%, Bob 28%, Carla 41%, Dan 22%, Eve 37%?"
    dataset = extract_inline_dataset(query)
    assert dataset is not None
    assert dataset.measures == ("Amount (%)",)
    assert dataset.units == ("percent",)
    assert ("Alice", Decimal("34")) in dataset.rows


def test_composition_wording_without_a_chart_verb_still_extracts_inline_data():
    # Live bug (2026-08-06): "What's the split of revenue by sales
    # channel..." and "What's the composition of our investment
    # portfolio..." both named an inline dataset but used none of
    # _DATA_OPERATION's existing trigger words ("chart"/"compare"/
    # "breakdown"/...), so extraction never even ran and the query fell
    # through to normal retrieval against unrelated reference sources.
    split_query = "What's the split of revenue by sales channel: Direct $450,000, Partner $220,000, Online $180,000, Retail $95,000?"
    assert extract_inline_dataset(split_query) is not None
    composition_query = (
        "What's the composition of our investment portfolio: Equities $2,400,000, "
        "Bonds $1,100,000, Real Estate $650,000, Cash $250,000?"
    )
    dataset = extract_inline_dataset(composition_query)
    assert dataset is not None
    assert ("Equities", Decimal("2400000")) in dataset.rows
