# Forgot-password endpoints (no sign-in required): request a code, check it,
# reset the password. See identity/password_reset.py for the rules.
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from app.core import supabase_admin
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.email import send_email
from app.core.rate_limit import limiter
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.identity import email_templates, password_reset

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/password", tags=["auth"])

# The same answer whether or not the address has an account.
GENERIC = "If an account exists for that email, a verification code has been sent."


def _reset_url() -> str:
    return f"{get_settings().FRONTEND_URL.rstrip('/')}/auth/forgot-password"


class EmailBody(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class CodeBody(EmailBody):
    code: str = Field(min_length=1, max_length=20)


class ResetBody(CodeBody):
    password: str = Field(min_length=1, max_length=200)


def _send_code(email: str, code: str) -> None:
    subject, html, text = email_templates.password_reset_code(
        email=email, code=code, ttl_minutes=get_settings().PASSWORD_RESET_TTL_MINUTES, reset_url=_reset_url())
    if not send_email(email, subject, html, text):
        log.warning("Password reset code could not be emailed")


def _send_changed(email: str) -> None:
    changed = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    subject, html, text = email_templates.password_changed(
        email=email, changed_at=changed, sign_in_url=f"{get_settings().FRONTEND_URL.rstrip('/')}/login")
    send_email(email, subject, html, text)


@router.post("/forgot")
@limiter.limit("5/5minutes")
async def forgot(request: Request, body: EmailBody, background: BackgroundTasks) -> dict:
    # The server's own session: the users table is under RLS and nobody is
    # signed in yet. Only the account's own row is touched.
    async with AsyncSessionLocal() as db:
        issued = await password_reset.request_code(db, body.email)
        if issued is not None:
            user, code = issued
            await record_event_async(db, tenant_id=user.tenant_id, event_name="auth.password_reset_requested",
                                     emitting_service="identity", actor_id=user.id, subject_type="user_account",
                                     subject_id=user.id, payload={"channel": "email_code"})
            background.add_task(_send_code, user.email, code)
    settings = get_settings()
    return {"message": GENERIC, "expires_in_minutes": settings.PASSWORD_RESET_TTL_MINUTES,
            "code_length": password_reset.CODE_DIGITS}


@router.post("/verify")
@limiter.limit("10/5minutes")
async def verify(request: Request, body: CodeBody) -> dict:
    async with AsyncSessionLocal() as db:
        try:
            await password_reset.verify(db, body.email, body.code)
        except password_reset.ResetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": "Code verified."}


@router.post("/reset")
@limiter.limit("10/5minutes")
async def reset(request: Request, body: ResetBody, background: BackgroundTasks) -> dict:
    async with AsyncSessionLocal() as db:
        try:
            user = await password_reset.reset(
                db, body.email, body.code, body.password,
                set_password=lambda uid, pw: supabase_admin.set_password(uid, pw))
        except password_reset.ResetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        # A changed password ends every existing session.
        try:
            await asyncio.to_thread(supabase_admin.revoke_all_sessions, user.id)
        except Exception as exc:  # noqa: BLE001 — the password is already changed
            log.warning("Session revocation after password reset failed (%s)", type(exc).__name__)
        await record_event_async(db, tenant_id=user.tenant_id, event_name="auth.password_reset_completed",
                                 emitting_service="identity", actor_id=user.id, subject_type="user_account",
                                 subject_id=user.id, payload={"channel": "email_code", "sessions_revoked": True})
        background.add_task(_send_changed, user.email)
    return {"message": "Password updated. You can now sign in."}
