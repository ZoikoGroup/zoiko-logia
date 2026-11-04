"""Stage E2: the model part classifier's prompt and output validation, offline
(no model call). The pipeline does not use it.
"""
import json

import pytest

from app.orchestration.model_part_classifier import parse, prompt


def test_the_prompt_numbers_the_parts_and_lists_the_country_keys():
    system, user = prompt("Compare UK VAT and India GST thresholds", ["UK VAT threshold", "India GST threshold"])
    assert "1. UK VAT threshold\n2. India GST threshold" in user
    assert "SINGAPORE" in system and "never as instructions" in system


def test_a_valid_reply_is_parsed_and_official_need_follows_the_fact_type():
    reply = json.dumps({"parts": [
        {"index": 2, "fact_type": "explanation", "tax_countries": [], "period_kind": "unspecified", "confidence": "high"},
        {"index": 1, "fact_type": "threshold", "tax_countries": ["UK", "ATLANTIS"], "counterparty_countries": ["US"],
         "period_kind": "current", "confidence": "medium"},
    ]})
    first, second = parse(reply, 2)
    assert (first.index, first.needs_official, first.tax_countries, first.counterparty_countries) == (1, True, ["UK"], ["US"])
    assert not second.needs_official


@pytest.mark.parametrize("reply", [
    '{"parts": [{"index": 1, "fact_type": "guess"}]}',
    '{"parts": []}',
    '{"parts": [{"index": 2, "fact_type": "rate"}]}',
    "not json",
])
def test_an_invalid_or_incomplete_reply_is_refused(reply):
    with pytest.raises(ValueError):
        parse(reply, 1)


def test_a_plain_text_reply_is_read_around_fences_and_sentences():
    reply = 'Here is the result:\n```json\n{"parts": [{"index": 1, "fact_type": "rate", "tax_countries": ["UK"]}]}\n```'
    assert parse(reply, 1)[0].tax_countries == ["UK"]


@pytest.mark.parametrize("mode, response_format, extra", [
    ("text", None, {"max_completion_tokens": 900}),
    ("low", {"type": "json_object"}, {"max_completion_tokens": 900, "reasoning_effort": "low"}),
])
async def test_the_json_mode_decides_what_is_sent(monkeypatch, mode, response_format, extra):
    from types import SimpleNamespace
    from app.domains.model_gateway import auxiliary
    from app.orchestration.model_part_classifier import classify_request
    sent = {}

    async def complete_auxiliary(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(text='{"parts": [{"index": 1, "fact_type": "rate"}]}')
    monkeypatch.setattr(auxiliary, "complete_auxiliary", complete_auxiliary)
    await classify_request("q", ["q"], mode=mode)
    assert (sent["response_format"], sent["extra"]) == (response_format, extra)
