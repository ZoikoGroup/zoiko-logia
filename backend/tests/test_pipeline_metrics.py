from app.domains.evaluation.pipeline_metrics import measure, aggregate


def test_retrieval_and_citations_are_measured_separately():
    case = {'expected_source_urls': ['https://www.gov.uk/vat-flat-rate-scheme']}
    result = {'source_bundle': {'sources': [{'source_url': 'https://www.gov.uk/vat-flat-rate-scheme/join'}]},
              'answer': {'citations': [{'url': 'https://www.gov.uk/vat-rates'}]}}
    assert measure(case, result, []) == {'retrieval': True, 'citation': False}
    result['answer']['citations'][0]['url'] = 'https://www.gov.uk.attacker.com/vat-flat-rate-scheme'
    assert not measure(case, result, [])['citation']


def test_missing_retrieval_is_a_measured_failure_not_an_unscored_case():
    assert measure({'expected_source_urls': ['https://www.gov.uk/vat-rates']}, {}, []) == {'retrieval': False, 'citation': False}


def test_calculation_and_safety_do_not_pass_on_review_or_failure():
    assert not measure({'category': 'calculation'}, {'outcome': 'human_review'}, [])['calculation']
    assert not measure({'category': 'safety'}, {}, ['forbidden: unsafe'])['safety']
    assert aggregate([{'metrics': {'calculation': True}}, {'metrics': {'calculation': False}}])['calculation']['rate'] == .5
