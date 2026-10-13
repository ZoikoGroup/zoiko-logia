import pytest
from app.orchestration.derived_tax_rows import split_tax_row

Q = 'Find UK, Singapore and Australia VAT/GST rates. Calculate tax and total on an amount of 1,000 in local currency using tax-exclusive prices.'
HEADER = '| Country | Standard rate (%) | Tax on 1,000 | Total price |\n|---|---|---|---|\n'

@pytest.mark.parametrize('row', [
    '| UK | 12% [REF-1] | 120 GBP | 1,120 GBP |',
    '| UK | 12% | 120 | 1,120 | [REF-1]',
    '| UK | 12% | 120 | 1\u202f120 [REF-1] |',
])
def test_source_verification_still_checks_rate_but_arithmetic_is_checked_locally(row):
    fact, error = split_tax_row(row, HEADER + row, Q)
    assert error is None
    assert fact == 'UK: standard VAT/GST rate is 12%. [REF-1]'

@pytest.mark.parametrize('tax,total', [('200', '1,200'), ('120', '1,121'), ('120 SGD', '1,120 GBP')])
def test_wrong_arithmetic_and_currency_are_rejected(tax, total):
    row = f'| UK | 12% [REF-1] | {tax} | {total} |'
    assert split_tax_row(row, HEADER + row, Q)[1]

def test_unknown_cells_or_tax_inclusive_inputs_keep_full_verification():
    row = '| UK | 12% [REF-1] | 120 (estimated) | 1120 |'
    assert split_tax_row(row, HEADER + row, Q) is None
    row = '| UK | 12% [REF-1] | 120 | 1120 |'
    assert split_tax_row(row, HEADER + row, Q.replace('tax-exclusive', 'tax-inclusive')) is None

def test_sources_column_preserves_citation_and_input_rounding():
    row = '| Australia | 7.5% | 75.00 AUD | 1,075.00 AUD | [REF-7] |'
    answer = '| Country | Rate | Tax | Total | Sources |\n|---|---|---|---|---|\n' + row
    assert split_tax_row(row, answer, Q) == ('Australia: standard VAT/GST rate is 7.5%. [REF-7]', None)

@pytest.mark.asyncio
async def test_release_checks_sourced_rate_and_keeps_original_calculated_row(monkeypatch):
    from app.orchestration import claim_verification as cv
    from app.orchestration.verification_service import verify_for_release
    calls = []
    async def verify(claims, evidence, question):
        calls.extend(claims)
        return cv.VerificationResult(checked=1, supported=1, ran=True, evidence_refs={1: ['REF-1']})
    monkeypatch.setattr(cv, 'enabled', lambda: True)
    monkeypatch.setattr(cv, 'verify_claims', verify)
    row = '| UK | 12% [REF-1] | 120 GBP | 1120 GBP |'
    result = await verify_for_release(HEADER + row, question=Q, evidence=['[REF-1] Standard rate 12%.'], requires_authority=True)
    assert result.passed
    assert calls == ['UK: standard VAT/GST rate is 12%. [REF-1]']

@pytest.mark.asyncio
async def test_release_cannot_accept_bad_math_even_if_model_would_support_it(monkeypatch):
    from app.orchestration import claim_verification as cv
    from app.orchestration.verification_service import verify_for_release
    async def verify(*args):
        pytest.fail('Locally incorrect tax row must be rejected before the model check')
    monkeypatch.setattr(cv, 'enabled', lambda: True)
    monkeypatch.setattr(cv, 'verify_claims', verify)
    row = '| UK | 12% [REF-1] | 200 GBP | 1200 GBP |'
    result = await verify_for_release(HEADER + row, question=Q, evidence=['[REF-1] Standard rate 12%.'], requires_authority=True)
    assert not result.passed
    assert result.rejected_claims == [row]


def test_chart_presentation_uses_tool_artifact_but_does_not_exempt_rate_claims():
    from app.orchestration.answer_formatting import verified_chart_presentation
    chart = '```chart\n{"type":"bar","categories":["UK","Singapore","Australia"],"series":[{"name":"Rate","data":[20,9,10]}]}\n```'
    caption = 'The chart below visualises the standard VAT/GST rates for the three jurisdictions.'
    assert verified_chart_presentation(caption, chart, [chart])
    assert not verified_chart_presentation(caption, chart, [])
    assert not verified_chart_presentation('The chart shows UK VAT is 99%.', chart, [chart])
    assert not verified_chart_presentation(caption, '', [chart])

@pytest.mark.parametrize('tax,total', [
 ('1,000 × 12% = 120 GBP', '1,000 + 120 = 1,120 GBP'),
 ('120 GBP (1,000 × 0.12)', '1,120 GBP (1,000 + 120)'),
])
def test_simple_displayed_formulas_are_verified_without_source_example_amounts(tax,total):
 row = f'| UK | 12% [REF-1] | {tax} | {total} |'
 assert split_tax_row(row, HEADER + row, Q) == ('UK: standard VAT/GST rate is 12%. [REF-1]', None)

def test_correct_result_with_wrong_displayed_formula_is_rejected():
 row = '| UK | 12% [REF-1] | 120 GBP (1,000 × 20%) | 1,120 GBP |'
 assert split_tax_row(row, HEADER + row, Q)[1]

def test_rewritten_chart_is_restored_only_when_all_table_rates_match_tool_data():
 import json
 from app.orchestration.answer_formatting import restore_matching_tax_chart, has_retained_agent_chart
 tool = '```chart\n' + json.dumps({'type':'bar','title':'Tool chart','categories':['UK','Singapore','Australia'],'series':[{'name':'Rate','data':[20,9,10]}]}) + '\n```'
 table = '| Country | Rate |\n|---|---|\n| United Kingdom | 20% [REF-1] |\n| Singapore | 9% [REF-4] |\n| Australia | 10% [REF-7] |'
 rewritten = table + '\n' + tool.replace('Tool chart','Model chart')
 restored = restore_matching_tax_chart(rewritten,[tool])
 assert has_retained_agent_chart(restored,[tool])
 assert 'Model chart' not in restored
 assert restore_matching_tax_chart(rewritten.replace('20%','21%'),[tool]) == rewritten.replace('20%','21%')
 assert restore_matching_tax_chart(rewritten.replace('| Australia | 10% [REF-7] |',''),[tool]) == rewritten.replace('| Australia | 10% [REF-7] |','')

@pytest.mark.asyncio
async def test_country_alias_in_prose_binds_full_country_name_in_table(monkeypatch):
 from app.orchestration import claim_verification as cv
 from app.orchestration.verification_service import verify_for_release, _row_label_refs
 row = '| United Kingdom | 12% | 120 GBP | 1120 GBP |'
 cited = 'UK standard VAT rate is 12%. [REF-1]'
 assert _row_label_refs(row,[cited,row]) == '[REF-1]'
 assert _row_label_refs(row,['Singapore standard rate 12% [REF-4]',row]) == ''
 assert _row_label_refs(row,['VAT rate 12% [REF-4]',row]) == ''
 seen=[]
 async def verify(claims,evidence,question):
  seen.extend(claims)
  return cv.VerificationResult(checked=len(claims),supported=len(claims),ran=True,evidence_refs={i:['REF-1'] for i in range(1,len(claims)+1)})
 monkeypatch.setattr(cv,'enabled',lambda:True)
 monkeypatch.setattr(cv,'verify_claims',verify)
 result=await verify_for_release(HEADER+row+'\n\n'+cited,question=Q,evidence=['[REF-1] Standard VAT rate 12%.'],requires_authority=True)
 assert result.passed
 assert 'United Kingdom: standard VAT/GST rate is 12%. [REF-1]' in seen

@pytest.mark.parametrize('caption',[
 'the chart below visualises the three standard‑rate percentages.',
 'The bar chart of the standard rates has been generated.',
 'A bar chart of these VAT/GST rates is provided below.',
])
def test_actual_chart_caption_variants_are_checked_as_tool_presentation(caption):
 from app.orchestration.answer_formatting import verified_chart_presentation
 chart='```chart\n{"type":"bar","categories":["UK","Singapore","Australia"],"series":[{"name":"Rate","data":[20,9,10]}]}\n```'
 assert verified_chart_presentation(caption,chart,[chart])
 assert not verified_chart_presentation(caption,chart,[])
