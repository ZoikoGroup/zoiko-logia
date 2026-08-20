from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.domains.kriton_workspace import retention


def _settings():
    return SimpleNamespace(
        DOCUMENT_RETENTION_DAYS=30,
        ARTIFACT_RETENTION_DAYS=7,
        FAILED_UPLOAD_RETENTION_HOURS=24,
    )


def test_retention_deadlines_follow_config(monkeypatch):
    monkeypatch.setattr(retention, "get_settings", _settings)
    now = datetime(2026, 8, 20, 10, 30, tzinfo=timezone.utc)

    assert retention.document_expiry(now) == now + timedelta(days=30)
    assert retention.artifact_expiry(now) == now + timedelta(days=7)
    assert retention.failed_upload_expiry(now) == now + timedelta(hours=24)


def test_retention_deadlines_are_timezone_aware(monkeypatch):
    monkeypatch.setattr(retention, "get_settings", _settings)

    assert retention.document_expiry().tzinfo is not None
    assert retention.artifact_expiry().tzinfo is not None


@pytest.mark.asyncio
async def test_local_retention_removes_physical_file(monkeypatch, tmp_path):
    data_root = tmp_path / "data"
    stored_file = data_root / "workspace_artifacts" / "tenant" / "report.pdf"
    stored_file.parent.mkdir(parents=True)
    stored_file.write_bytes(b"temporary report")
    monkeypatch.setattr(retention, "_BACKEND_ROOT", tmp_path)
    monkeypatch.setattr(retention, "_DATA_ROOT", data_root)
    row = SimpleNamespace(
        storage_provider="local",
        storage_bucket=None,
        storage_object_path=None,
        storage_path="data/workspace_artifacts/tenant/report.pdf",
    )

    await retention._remove_stored_file(row)

    assert not stored_file.exists()


@pytest.mark.asyncio
async def test_local_retention_rejects_path_outside_data(monkeypatch, tmp_path):
    monkeypatch.setattr(retention, "_BACKEND_ROOT", tmp_path)
    monkeypatch.setattr(retention, "_DATA_ROOT", tmp_path / "data")
    row = SimpleNamespace(
        storage_provider="local", storage_bucket=None,
        storage_object_path=None, storage_path="../outside.txt",
    )

    with pytest.raises(ValueError, match="escapes"):
        await retention._remove_stored_file(row)
