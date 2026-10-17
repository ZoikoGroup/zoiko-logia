"""Password reset by emailed code (ZoikoStream-style recovery).

Pins: no account enumeration (unknown addresses get no code), the code is
stored only as a keyed hash, it expires, works once, locks after too many
wrong tries, a resend supersedes the old code and is throttled, a weak new
password never burns the code, and Supabase refusing the password gives the
code back. Also the email escapes values and is skipped without a key.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import email as email_mod
from app.core import supabase_admin
from app.db.base import Base
from app.domains.identity import email_templates, password_reset
from app.domains.identity.models import PasswordResetChallenge, ServiceAccount, Tenant, User

NOW = datetime.now(timezone.utc)


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all([
            Tenant(id="t1", name="Acme"),
            User(id="u1", tenant_id="t1", email="ada@example.com", full_name="Ada", role="Learner", is_active=True),
            User(id="off", tenant_id="t1", email="gone@example.com", full_name="Gone", role="Learner", is_active=False),
            User(id="svc", tenant_id="t1", email="svc-1@service-accounts.invalid", full_name="erp", role="System Auditor"),
            ServiceAccount(id="svc", tenant_id="t1", name="erp", owner_user_id="u1", created_by="u1"),
        ])
        await session.commit()
        yield session
    await engine.dispose()


async def test_codes_are_issued_only_to_active_people_and_stored_hashed(db) -> None:
    assert await password_reset.request_code(db, "nobody@example.com") is None
    assert await password_reset.request_code(db, "gone@example.com") is None
    assert await password_reset.request_code(db, "svc-1@service-accounts.invalid") is None
    user, code = await password_reset.request_code(db, "  ADA@example.com ", now=NOW)
    assert user.id == "u1" and len(code) == 6 and code.isdigit()
    row = (await db.execute(select(PasswordResetChallenge))).scalar_one()
    assert code not in row.code_hash and row.code_hash != code


async def test_resend_is_throttled_and_supersedes_the_old_code(db) -> None:
    _, first = await password_reset.request_code(db, "ada@example.com", now=NOW)
    assert await password_reset.request_code(db, "ada@example.com", now=NOW + timedelta(seconds=10)) is None
    _, second = await password_reset.request_code(db, "ada@example.com", now=NOW + timedelta(seconds=61))
    if first != second:
        outcome, _, _ = await password_reset.check_code(db, "ada@example.com", first, now=NOW + timedelta(seconds=62))
        assert outcome == password_reset.INVALID, "the superseded code no longer works"
    outcome, _, _ = await password_reset.check_code(db, "ada@example.com", second, now=NOW + timedelta(seconds=62))
    assert outcome == password_reset.VALID


async def test_wrong_codes_lock_and_expired_codes_fail(db) -> None:
    _, code = await password_reset.request_code(db, "ada@example.com", now=NOW)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(4):
        assert (await password_reset.check_code(db, "ada@example.com", wrong))[0] == password_reset.INVALID
    assert (await password_reset.check_code(db, "ada@example.com", wrong))[0] == password_reset.LOCKED
    assert (await password_reset.check_code(db, "ada@example.com", code))[0] == password_reset.LOCKED, "locked even for the right code"

    _, code2 = await password_reset.request_code(db, "ada@example.com", now=NOW + timedelta(minutes=2))
    late = NOW + timedelta(minutes=30)
    assert (await password_reset.check_code(db, "ada@example.com", code2, now=late))[0] == password_reset.INVALID


async def test_reset_spends_the_code_once_and_never_on_a_weak_password(db) -> None:
    _, code = await password_reset.request_code(db, "ada@example.com", now=NOW)
    calls = []
    with pytest.raises(password_reset.ResetError, match="at least 8"):
        await password_reset.reset(db, "ada@example.com", code, "weak", set_password=lambda *a: calls.append(a))
    assert calls == [], "a weak password never reaches Supabase"

    user = await password_reset.reset(db, "ada@example.com", code, "Secure123", set_password=lambda *a: calls.append(a))
    assert user.id == "u1" and calls == [("u1", "Secure123")]
    with pytest.raises(password_reset.ResetError, match="Invalid or expired"):
        await password_reset.reset(db, "ada@example.com", code, "Secure456", set_password=lambda *a: calls.append(a))


async def test_password_refused_by_supabase_gives_the_code_back(db) -> None:
    _, code = await password_reset.request_code(db, "ada@example.com", now=NOW)

    def refuse(*_):
        raise supabase_admin.PasswordRejectedError("Password is known to be weak and easy to guess")
    with pytest.raises(password_reset.ResetError, match="easy to guess"):
        await password_reset.reset(db, "ada@example.com", code, "Password123", set_password=refuse)
    await password_reset.reset(db, "ada@example.com", code, "Better-Choice9", set_password=lambda *a: None)


async def test_admin_api_unavailable_is_a_clear_error_and_keeps_the_code(db) -> None:
    # A masked/missing service-role key used to surface as a raw 500 that had
    # already burned the code.
    _, code = await password_reset.request_code(db, "ada@example.com", now=NOW)

    def unconfigured(*_):
        raise supabase_admin.SupabaseNotConfiguredError("masked key")
    with pytest.raises(password_reset.ResetUnavailableError):
        await password_reset.reset(db, "ada@example.com", code, "Secure123", set_password=unconfigured)
    await password_reset.reset(db, "ada@example.com", code, "Secure123", set_password=lambda *a: None)


def test_email_is_branded_escaped_and_skipped_without_a_key(monkeypatch) -> None:
    subject, html, text = email_templates.password_reset_code(
        email="<script>@x.com", code="123456", ttl_minutes=15, reset_url="https://app.example/auth/forgot-password")
    assert "123456" not in subject, "the code never appears in the subject line"
    assert "1 2 3 4 5 6" in html and "123456" in text
    assert "<script>" not in html and "ZoikoLogia" in html and "#16799a" in html
    monkeypatch.setattr(email_mod.get_settings(), "RESEND_API_KEY", "")
    assert email_mod.send_email("a@example.com", subject, html, text) is False
