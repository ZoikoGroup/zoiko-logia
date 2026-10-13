from decimal import Decimal
from unittest.mock import AsyncMock
from app.orchestration.calculations.engine import calculate_from_query
from app.orchestration.fx_profit import latest_fx_requested
from app.orchestration.official_evidence import official_pages
from app.orchestration import claim_verification as cv
from app.orchestration.verification_service import verify_for_release

def test_current_assets_never_require_fx():
    assert not latest_fx_requested('Current assets ₹250,000, liabilities ₹100,000. Debt £300,000, equity £200,000. Ratios?')
    assert not latest_fx_requested("Convert US$4,000 into INR for 31 December 2024. Do not use today's rate.")
    assert latest_fx_requested('Using the latest available USD/INR rate, convert US$4,000 into rupees.')
    assert latest_fx_requested('Find the latest USD/INR rate.')

def test_supplied_gst_split_runs_without_model_or_retrieval():
    result = calculate_from_query('Calculate CGST and SGST on an intra-state sale of ₹40,000 at 12%')
    assert result.status == 'success'
    assert {o.name: o.value for o in result.outputs} == {'cgst': Decimal(2400), 'sgst': Decimal(2400), 'total_gst': Decimal(4800)}
    assert '6' in result.steps[0]
    assert not calculate_from_query('Calculate CGST and SGST on an inter-state sale of ₹40,000 at 12%').matched

def test_direct_pages_match_country_and_supply_type():
    assert any('iras.gov.sg' in url for _,url in official_pages('Singapore GST rate in 2026?'))
    assert any('mof.gov.ae' in url for _,url in official_pages('What is the VAT rate in UAE?'))
    assert any('mysst' in url for _,url in official_pages('What is the GST rate in Malaysia?'))
    urls = [url for _, url in official_pages("I'm a freelance developer in Bangalore billing a US client ₹30 lakh a year. Do I need GST registration and do I charge GST?")]
    assert any("IGST-bill-e.html" in url for url in urls)
    assert any("amendment-act_2018" in url for url in urls)
    assert any("GST-An-Update" in url for url in urls)
    assert not official_pages('What is Canadian GST?')

async def test_ring_fence_misapplication_cannot_pass_even_if_judge_accepts(monkeypatch):
    monkeypatch.setenv('CLAIM_VERIFICATION', 'on')
    judge = AsyncMock(return_value=cv.VerificationResult(checked=1,supported=1,ran=True,evidence_refs={1:['REF-1']}))
    monkeypatch.setattr(cv, 'verify_claims', judge)
    result = await verify_for_release('The main ring-fence corporation tax rate for profits over £250,000 is 30% [REF-1].',
        question='UK corporation tax rate for a company with £300,000 profit?', evidence=['[REF-1] Ring-fence 30%'], requires_authority=True)
    assert not result.passed and result.rejected_claims
    judge.assert_not_called()


def test_numbered_calculations_keep_inputs_isolated_and_all_answers():
    from app.orchestration.calculations.engine import calculation_markdown
    from app.orchestration.calculation_service import validate_answer_calculations
    question = ('7 Current assets ₹2,50,000, current liabilities ₹1,00,000, inventory ₹50,000. Current and quick ratio? '
                '8 Total liabilities £300,000, equity £200,000. Debt-to-equity? '
                '9 Cost £80, selling price £100. Markup and margin? '
                '10 Fixed costs ₹50,000, price ₹25/unit, variable cost ₹15/unit. Break-even units? '
                '11 Sales grew from ₹1,00,000 to ₹1,50,000 over 3 years. CAGR? '
                '12 Simple interest on ₹50,000 at 8% for 3 years '
                '13 ₹10,000 invested at 8% compounded annually for 10 years '
                '14 EMI on ₹10,00,000 at 10% for 5 years '
                '15 Machine cost £50,000, residual £5,000, life 5 years. Straight-line depreciation?')
    result=calculate_from_query(question)
    assert result.status=='success' and len(result.outputs)==12
    values={o.name:o.display_value for o in result.outputs}
    assert values['Question 7 current ratio']=='2.50:1'
    assert values['Question 7 quick ratio']=='2.00:1'
    assert values['Question 11 CAGR']=='14.47%'
    assert values['Question 14 monthly EMI']=='₹21,247.04'
    assert values['Question 15 annual depreciation']=='£9,000.00'
    assert not validate_answer_calculations(calculation_markdown(result))


def test_numbered_batch_with_unknown_question_does_not_return_partial_answer():
    result=calculate_from_query('1 Total liabilities £300,000, equity £200,000. Debt-to-equity? 2 What is the current VAT threshold?')
    assert not result.matched


def test_gst_split_rejects_negative_and_ambiguous_inputs():
    assert calculate_from_query('Calculate CGST and SGST on an intra-state sale of ₹40,000 at -12%').error_code=='INVALID_PERCENTAGE'
    assert not calculate_from_query('Calculate CGST and SGST on intra-state sales of ₹40,000 and ₹50,000 at 12%').matched
    assert not calculate_from_query('Calculate CGST and SGST on an intra-state sale of ₹40,000 each at 12%').matched

async def test_official_read_keeps_actual_page_evidence_and_fails_soft(monkeypatch):
    from app.orchestration.official_evidence import official_sources
    from app.orchestration import websearch
    text='<html><p>The current GST rate for Singapore is 9%. Taxable supplies are charged at this current rate unless exempt or zero-rated.</p></html>'
    monkeypatch.setattr(websearch, '_read_html', AsyncMock(return_value=text))
    sources=await official_sources('Singapore GST rate?')
    assert len(sources)==1 and 'current GST rate for Singapore is 9%' in sources[0].snippet
    assert sources[0].provider=='IRAS' and sources[0].fetched_at
    monkeypatch.setattr(websearch, '_read_html', AsyncMock(side_effect=RuntimeError('offline')))
    assert await official_sources('Singapore GST rate?')==[]

async def test_unqualified_state_services_threshold_fails_even_if_judge_accepts(monkeypatch):
    monkeypatch.setenv('CLAIM_VERIFICATION','on')
    judge=AsyncMock(return_value=cv.VerificationResult(checked=1,supported=1,ran=True,evidence_refs={1:['REF-1']}))
    monkeypatch.setattr(cv,'verify_claims',judge)
    result=await verify_for_release('The threshold is ₹10 lakh for the supply of services [REF-1].',
        question='What is GST registration threshold in India?',evidence=['[REF-1] Threshold 10 lakh for named states'],requires_authority=True)
    assert not result.passed
    judge.assert_not_called()


def test_registration_and_export_searches_cover_both_requested_topics():
    from app.orchestration.websearch import evidence_search_queries
    from app.orchestration.source_taxonomy import allowed_domains,TAX
    parts=evidence_search_queries("I'm a freelance developer in Bangalore billing a US client ₹30 lakh a year. Do I need GST registration and do I charge GST?")
    assert any('registration' in q for q in parts)
    assert any('section 16' in q and 'zero rated' in q for q in parts)
    assert any('section 2(6)' in q for q in parts)
    assert {'cbic-gst.gov.in','gstcouncil.gov.in','indiacode.nic.in'} <= set(allowed_domains('INDIA',{TAX}))

async def test_monthly_registration_liability_cannot_become_composition_eligibility(monkeypatch):
    monkeypatch.setenv('CLAIM_VERIFICATION','on')
    judge=AsyncMock(return_value=cv.VerificationResult(checked=1,supported=1,ran=True,evidence_refs={1:['REF-1']}))
    monkeypatch.setattr(cv,'verify_claims',judge)
    result=await verify_for_release('A taxpayer whose monthly output tax liability is ₹2.5 lakh may opt for the composition scheme [REF-1].',
        question='What is GST registration threshold in India?',evidence=['[REF-1] Registration option under Rule 14A'],requires_authority=True)
    assert not result.passed
    judge.assert_not_called()


def test_quoted_vat_threshold_uses_current_hmrc_not_old_freeze_notice():
    from types import SimpleNamespace
    from app.orchestration.websearch import WebSource
    from app.orchestration.uk_vat_headroom import source_grounded_threshold_correction
    source=WebSource(title='HMRC',url='https://www.gov.uk/register-for-vat',freshness='current',
        snippet='You must register if your total taxable turnover for the last 12 months goes over £90,000.')
    refs=[SimpleNamespace(url=source.url,ref_id='REF-2')]
    result=source_grounded_threshold_correction('My accountant says the VAT threshold is £85,000. Who is right?',[source],refs)
    assert '£90,000' in result and 'does not match' in result and '[REF-2]' in result
    assert source_grounded_threshold_correction('What was the VAT threshold in 2020?',[source],refs) is None


def test_strengthened_export_eval_rejects_threshold_only_answer():
    import json
    from pathlib import Path
    from scripts.run_baseline_eval import score
    case=next(c for c in json.loads((Path(__file__).parents[1]/'evals/session_regression.json').read_text())['cases'] if c['id']=='scn-gst-export-services')
    assert score(case,{'outcome':'answered','answer':{'text':'GST threshold is 20 lakh. The sources do not establish the export treatment.','citations':[]}})


def test_current_rate_extraction_requires_explicit_current_authority_fact():
    from datetime import datetime,timezone
    from types import SimpleNamespace
    from app.orchestration.websearch import WebSource
    from app.orchestration.official_evidence import source_grounded_current_rate
    today=datetime.now(timezone.utc)
    url='https://www.iras.gov.sg/taxes/goods-services-tax-(gst)/basics-of-gst/current-gst-rates'
    source=WebSource(title='IRAS',url=url,snippet='The current GST rate in Singapore is 9%.',freshness='current',fetched_at=today.isoformat())
    citations=[SimpleNamespace(url=url,ref_id='REF-3')]
    assert '9%' in source_grounded_current_rate(f'Singapore GST rate in {today.year}?',[source],citations)
    assert source_grounded_current_rate('Singapore GST rate in 2023?',[source],citations) is None
    assert source_grounded_current_rate('Compare Singapore and Australia GST rates.',[source],citations) is None
    assert source_grounded_current_rate('Explain the Singapore GST rate and exceptions.',[source],citations) is None
    source.snippet='In 2018 the GST rate was 7%.'
    assert source_grounded_current_rate('Singapore GST rate?',[source],citations) is None


def test_export_coverage_requires_qualification_and_lut():
    from app.orchestration.input_requirements import gst_answer_gaps
    question="I'm a freelance developer in Bangalore billing a US client ₹30 lakh a year. Do I need GST registration and do I charge GST?"
    assert gst_answer_gaps(question,'Turnover exceeds 20 lakh. Services to a foreign client are zero-rated.')
    assert not gst_answer_gaps(question,'Turnover exceeds 20 lakh. If the export-of-services conditions are met, the supply is zero-rated. A Letter of Undertaking (LUT) or bond is required to export without payment of IGST.')


def test_export_eval_accepts_full_name_of_lut():
    import json
    from pathlib import Path
    from scripts.run_baseline_eval import score
    case=next(c for c in json.loads((Path(__file__).parents[1]/'evals/session_regression.json').read_text())['cases'] if c['id']=='scn-gst-export-services')
    result={'outcome':'answered','answer':{'text':'20 lakh is the registration threshold. Qualifying exports are zero-rated; use a letter of undertaking for export without payment of IGST.','citations':[]}}
    assert not score(case,result)


def test_export_explanation_is_bound_to_all_required_source_rules():
    from types import SimpleNamespace
    from app.orchestration.websearch import WebSource
    from app.orchestration.gst_export import source_grounded_export
    q="I'm a freelance developer in Bangalore billing a US client ₹30 lakh a year. Do I need GST registration and do I charge GST?"
    sources=[WebSource(title='CBIC',url='https://cbic-gst.gov.in/pdf/01062019-GST-An-Update.pdf',snippet='Threshold for suppliers of services would be Rs. 20 lakhs and Rs. 10 lakhs (for States of Manipur, Mizoram, Nagaland and Tripura).'),
             WebSource(title='Act',url='https://cag.gov.in/gst-act.pdf',snippet='Zero-rated supplies include export of goods or services or both. Export without payment of IGST requires a LUT or bond.')]
    refs=[SimpleNamespace(url=s.url,ref_id=f'REF-{i+1}') for i,s in enumerate(sources)]
    result=source_grounded_export(q,sources,refs)
    assert result and '20 lakh' in result and 'If the supply qualifies' in result and 'LUT' in result
    assert '[REF-1]' in result and '[REF-2]' in result
    assert source_grounded_export(q,sources[:1],refs) is None
    assert source_grounded_export(q,[],refs) is None
    assert source_grounded_export(q.replace('Bangalore','London'),sources,refs) is None


def test_exact_reported_three_part_calculation():
    question = ('Answer each separately: 1 Current assets ₹250,000, current liabilities ₹100,000 and inventory ₹50,000. Calculate current and quick ratios. '
                '2 Total liabilities £300,000 and equity £200,000. Calculate debt-to-equity. '
                '3 Sales grew from ₹100,000 to ₹150,000 over three years. Calculate CAGR.')
    result = calculate_from_query(question)
    assert result.status == 'success'
    assert [o.display_value for o in result.outputs] == ['2.50:1', '2.00:1', '1.50:1', '14.47%']


def test_unknown_batch_part_cannot_borrow_other_parts_inputs():
    question = ('Answer each separately: 1 Current assets ₹250,000, current liabilities ₹100,000 and inventory ₹50,000. Calculate current and quick ratios. '
                '2 Total liabilities £300,000 and equity £200,000. Calculate debt-to-equity. '
                '3 Explain an unknown calculation.')
    assert not calculate_from_query(question).matched


def test_coverage_detects_pruned_scenario_and_replacement():
    from app.orchestration.answer_coverage import requested_topic_gaps
    q = 'For an ordinary UK company compare corporation tax rates at profits of £300,000 and £40,000.'
    assert requested_topic_gaps(q, '| £300,000 | 25% |') == ['corporation-tax scenario for £40,000']
    assert not requested_topic_gaps(q, '| £300,000 | 25% |\n| £40,000 | 19% |')
    assert requested_topic_gaps('Does Malaysia currently use GST? Explain what replaced it.', 'GST was abolished.')
    assert not requested_topic_gaps('Does Malaysia currently use GST? Explain what replaced it.', 'GST was replaced by SST.')


def test_lut_alone_is_not_export_qualification():
    from app.orchestration.answer_coverage import requested_topic_gaps
    q = 'My US client buys services. Explain when services qualify as exports.'
    assert len(requested_topic_gaps(q, 'Use an LUT if exports qualify.')) == 5
    assert not requested_topic_gaps(q, 'Supplier located in India; recipient outside India; place of supply outside India; payment in convertible foreign exchange; not establishments of the same person.')


def test_replacement_requires_explicit_repeal_and_successor_date():
    from types import SimpleNamespace
    from app.orchestration.official_evidence import source_grounded_tax_replacement
    from app.orchestration.websearch import WebSource
    url = 'https://mysst.customs.gov.my/faq-sales-tax/'
    ref = SimpleNamespace(url=url, ref_id='REF-1')
    source = WebSource(title='Customs', url=url, snippet='When the GST Act 2014 is repealed, GST registration ceases. SST comes into effect from 1st September 2018.')
    answer = source_grounded_tax_replacement('Does Malaysia currently use GST? Explain what replaced it.', [source], [ref])
    assert 'SST' in answer and '1st September 2018' in answer and '[REF-1]' in answer
    source.snippet = 'GST rate became zero in June 2018.'
    assert source_grounded_tax_replacement('Does Malaysia currently use GST?', [source], [ref]) is None


async def test_lut_refund_confusion_rejected_even_when_judge_accepts(monkeypatch):
    monkeypatch.setenv('CLAIM_VERIFICATION', 'on')
    judge = AsyncMock(return_value=cv.VerificationResult(checked=1, supported=1, ran=True, evidence_refs={1:['REF-1']}))
    monkeypatch.setattr(cv, 'verify_claims', judge)
    result = await verify_for_release('You may export services without charging IGST by furnishing an LUT and later claim a refund of the IGST paid [REF-1].',
        question='My US client buys services. Explain exports and LUT.', evidence=['[REF-1] LUT without IGST; alternatively pay IGST and refund IGST paid.'], requires_authority=True)
    assert not result.passed
    judge.assert_not_called()


async def test_non_ring_fence_question_does_not_enable_special_rate(monkeypatch):
    monkeypatch.setenv('CLAIM_VERIFICATION', 'on')
    judge = AsyncMock(return_value=cv.VerificationResult(checked=1, supported=1, ran=True, evidence_refs={1:['REF-1']}))
    monkeypatch.setattr(cv, 'verify_claims', judge)
    result = await verify_for_release('The ring-fence corporation tax rate for profits over £250,000 is 30% [REF-1].',
        question='Compare corporation tax for an ordinary UK company with non-ring-fence profits.', evidence=['[REF-1] Ring-fence 30%.'], requires_authority=True)
    assert not result.passed
    judge.assert_not_called()


def test_exact_export_question_requires_all_five_conditions_and_amendment():
    from types import SimpleNamespace
    from app.orchestration.websearch import WebSource
    from app.orchestration.gst_export import source_grounded_export
    from app.orchestration.answer_coverage import requested_topic_gaps
    from app.orchestration.input_requirements import gst_answer_gaps
    question = ('I’m a freelance developer in Bangalore billing a US client ₹30 lakh annually. Assuming this is my aggregate service turnover, '
                'do I need GST registration? Explain when the services qualify as exports and when I can invoice without IGST using an LUT or bond. Cite official sources.')
    sources = [
        WebSource(title='CBIC', url='https://cbic-gst.gov.in/pdf/01062019-GST-An-Update.pdf', snippet='suppliers of services would be Rs. 20 lakhs and Rs. 10 lakhs (for States of Manipur, Mizoram, Nagaland and Tripura).'),
        WebSource(title='Act', url='https://cbic-gst.gov.in/hindi/IGST-bill-e.html', snippet='supplier of service is located in India; recipient of service is located outside India; place of supply of service is outside India; payment received in convertible foreign exchange; not merely establishments of a distinct person. Zero rated supply includes export of goods or services or both. Letter of Undertaking without payment of integrated tax for export.'),
        WebSource(title='Amendment', url='https://gstcouncil.gov.in/amendment.pdf', snippet='or in Indian rupees wherever permitted by the Reserve Bank of India'),
    ]
    refs = [SimpleNamespace(url=s.url, ref_id=f'REF-{i+1}') for i,s in enumerate(sources)]
    answer = source_grounded_export(question, sources, refs)
    assert answer and 'financial year' in answer
    assert not requested_topic_gaps(question, answer)
    assert not gst_answer_gaps(question, answer)
    assert source_grounded_export(question, sources[:2], refs) is None
    assert 'refund of IGST paid' not in answer


async def test_blanket_interstate_services_registration_rejected(monkeypatch):
    monkeypatch.setenv('CLAIM_VERIFICATION', 'on')
    judge = AsyncMock(return_value=cv.VerificationResult(checked=1, supported=1, ran=True, evidence_refs={1:['REF-1']}))
    monkeypatch.setattr(cv, 'verify_claims', judge)
    result = await verify_for_release('Inter-state taxable supplies of services require GST registration regardless of turnover [REF-1].',
        question='India GST registration thresholds and compulsory registration?', evidence=['[REF-1] Service suppliers below the applicable limit are exempt.'], requires_authority=True)
    assert not result.passed
    judge.assert_not_called()


def test_compulsory_registration_coverage_requires_core_categories_and_exemptions():
    from app.orchestration.answer_coverage import requested_topic_gaps
    q = 'Explain India GST compulsory-registration conditions.'
    assert requested_topic_gaps(q, 'Section 24 requires registration.')
    assert requested_topic_gaps(q, 'Reverse charge, casual taxable persons and non-resident taxable persons must register.')
    assert not requested_topic_gaps(q, 'Reverse charge, casual taxable persons and non-resident taxable persons: subject to notified exemptions.')


def test_nonconsecutive_and_lowercase_batches_cannot_mix_inputs():
    q = '1) current assets ₹250,000, current liabilities ₹100,000. Calculate current ratio. 3) total liabilities £300,000 and equity £200,000. Calculate debt-to-equity.'
    # Solved separately, each with its own inputs (it used to be refused).
    assert [o.display_value for o in calculate_from_query(q).outputs] == ["2.50:1", "1.50:1"]
    q = '1) total liabilities £300,000 and equity £200,000. Calculate debt-to-equity. 2) explain an unknown calculation.'
    assert not calculate_from_query(q).matched


def test_source_bound_compulsory_registration_rejects_incomplete_statute():
    from types import SimpleNamespace
    from app.orchestration.websearch import WebSource
    from app.orchestration.gst_registration import source_grounded_registration
    q = 'Explain India GST registration thresholds for services and goods with compulsory-registration conditions.'
    source = WebSource(title='CBIC', url='https://cbic-gst.gov.in/pdf/01062019-GST-An-Update.pdf', snippet='suppliers of services would be Rs. 21 lakhs and Rs. 11 lakhs (for States of Example). suppliers of goods would be Rs. 41 lakhs and Rs. 21 lakhs (in the States of Example). Suppliers of services making inter State supplies and e-commerce platforms.')
    categories = ['i','ii','iii','iv','v','vi','vii','viii','ix','x','xi','xia','xii']
    text = '23. Persons not liable for registration. 24. Compulsory registration in certain cases. ' + ' '.join(f'({item}) category {item}' for item in categories)
    act = WebSource(title='Act', url='https://www.indiacode.nic.in/indiacode/bitstream/123456789/15689/1/A2017-12.pdf', snippet=text)
    refs = [SimpleNamespace(url=s.url, ref_id=f'REF-{i+1}') for i,s in enumerate([source,act])]
    answer = source_grounded_registration(q, [source,act], refs)
    assert answer and '₹21 lakh' in answer and '₹41 lakh' in answer and 'category xia' in answer
    act.snippet = act.snippet.replace('(xia)', '(xiv)')
    assert source_grounded_registration(q, [source,act], refs) is None
