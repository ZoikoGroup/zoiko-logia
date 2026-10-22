import httpx
import pytest
from groq import APITimeoutError
from app.domains.model_gateway.errors import provider_request_failure, ProviderTimedOut


@pytest.mark.parametrize('error', [TimeoutError(), httpx.ReadTimeout('synthetic timeout'),
                                  APITimeoutError(request=httpx.Request('POST', 'https://synthetic.invalid'))])
def test_provider_timeouts_have_specific_safe_classification(error):
    classified = provider_request_failure(error)
    assert isinstance(classified, ProviderTimedOut)
    assert classified.code == 'provider_timeout'
    assert 'timed out' in classified.user_message
