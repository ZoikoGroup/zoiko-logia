"""Exercise real authentication/RBAC and form handling at the existing endpoint."""
from tests.offline_http_support import offline_http  # noqa: F401


async def test_source_approval_endpoint_requires_auth_and_verified_individual(offline_http):
    path="/api/v1/sources/missing/versions/missing/approve"
    unauth=await offline_http.client.post(path)
    assert unauth.status_code == 401
    auth=await offline_http.client.post(path,headers={"Authorization":"Bearer offline-actor-a"})
    assert auth.status_code == 403
    assert "reviewer" in auth.json()["detail"].lower()


async def test_submission_form_preserves_distinct_reporting_period(offline_http):
    response=await offline_http.client.post("/api/v1/sources",
        headers={"Authorization":"Bearer offline-actor-a"},
        data={"category":"standards","title":"Test report","source_class":"report",
              "reporting_period_start":"2024-01-01","reporting_period_end":"2024-12-31",
              "published_at":"2025-02-01T00:00:00Z"})
    assert response.status_code == 200, response.text
    version=response.json()["latest_version"]
    assert version["reporting_period_start"] == "2024-01-01"
    assert version["reporting_period_end"] == "2024-12-31"
    assert version["effective_from"] is None and version["approved_by"] is None
    assert version["status"] == "PROPOSED"


async def test_invalid_reporting_period_form_is_rejected(offline_http):
    response=await offline_http.client.post("/api/v1/sources",
        headers={"Authorization":"Bearer offline-actor-a"},
        data={"category":"standards","title":"Invalid report","source_class":"report",
              "reporting_period_start":"2025-01-01","reporting_period_end":"2024-12-31"})
    assert response.status_code == 422
