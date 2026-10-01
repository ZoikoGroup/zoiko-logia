from unittest.mock import AsyncMock, patch

import pytest

from app.orchestration.service import _record_answer_source_usages


@pytest.mark.asyncio
async def test_missing_source_bundle_does_not_crash_answer_finalisation():
    with patch(
        "app.orchestration.service.record_source_usages", new_callable=AsyncMock
    ) as record:
        await _record_answer_source_usages(
            AsyncMock(), source_bundle=None, tenant_id="tenant-a", query_id="qry-1"
        )

    record.assert_not_awaited()
