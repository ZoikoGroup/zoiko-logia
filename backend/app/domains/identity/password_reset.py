"""Password reset by emailed code, modelled on ZoikoStream's recovery flow.

1. request: a 6-digit code is emailed (through our own Resend sender, so it
   arrives from "ZoikoLogia" and is not subject to Supabase's mailer limits).
2. verify: the code is checked without spending it.
3. reset: the code is checked again and spent, the new password is set in
   Supabase Auth, every session is signed out, and a confirmation is sent.

Properties:
- The response never reveals whether an address has an account.
- Only a keyed hash of the code is stored (HMAC with a server secret and a
  per-code salt): a 6-digit code is trivial to brute-force from a plain hash.
- A code expires (PASSWORD_RESET_TTL_MINUTES), works once, and locks after
  PASSWORD_RESET_MAX_ATTEMPTS wrong tries. A new request supersedes the old
  code. A new code is not sent more than once a minute per account.
- The password is validated before the code is spent, so a typo in the new
  password never burns the code.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import supabase_admin
from app.core.config import get_settings
from app.domains.identity.models import PasswordResetChallenge, ServiceAccount, User

CODE_DIGITS = 6
RESEND_COOLDOWN = timedelta(seconds=60)
PASSWORD_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$")
PASSWORD_RULE = "Password must be at least 8 characters with an uppercase letter, a lowercase letter, and a number."

VALID, INVALID, LOCKED = "valid", "invalid", "locked"


class ResetError(ValueError):
    """A reset the rules refuse; the message is safe to show."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: datetime | None) -> datetime | None:
    return None if v is None else (v if v.tzinfo else v.replace(tzinfo=timezone.utc))


def _hash(code: str, salt: str) -> str:
    pepper = (get_settings().SUPABASE_SERVICE_ROLE_KEY or "zoikologia-reset").encode()
    return hmac.new(pepper, f"{salt}:{code}".encode(), hashlib.sha256).hexdigest()


async def _account(db: AsyncSession, email: str) -> User | None:
    """An active person with this email; never a service account."""
    user = (await db.execute(select(User).where(func.lower(User.email) == email.strip().lower()))).scalar_one_or_none()
    if user is None or not user.is_active or (await db.get(ServiceAccount, user.id)) is not None:
        return None
    return user


async def _active(db: AsyncSession, user_id: str) -> PasswordResetChallenge | None:
    return (await db.execute(
        select(PasswordResetChallenge).where(
            PasswordResetChallenge.user_id == user_id, PasswordResetChallenge.consumed_at.is_(None),
            PasswordResetChallenge.superseded_at.is_(None))
        .order_by(PasswordResetChallenge.created_at.desc()).limit(1)
    )).scalar_one_or_none()


async def request_code(db: AsyncSession, email: str, *, now: datetime | None = None) -> tuple[User, str] | None:
    """Issue a code for this address, or None when nothing is to be sent
    (unknown address, inactive account, or a code sent in the last minute).
    The caller answers identically either way."""
    now = now or _now()
    user = await _account(db, email)
    if user is None:
        return None
    current = await _active(db, user.id)
    if current is not None and now - _aware(current.created_at) < RESEND_COOLDOWN:
        return None
    await db.execute(update(PasswordResetChallenge).where(
        PasswordResetChallenge.user_id == user.id, PasswordResetChallenge.consumed_at.is_(None),
        PasswordResetChallenge.superseded_at.is_(None)).values(superseded_at=now))
    code = f"{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}"
    salt = secrets.token_hex(16)
    db.add(PasswordResetChallenge(
        user_id=user.id, code_hash=_hash(code, salt), salt=salt, created_at=now, attempts=0,
        expires_at=now + timedelta(minutes=get_settings().PASSWORD_RESET_TTL_MINUTES)))
    await db.commit()
    return user, code


async def check_code(db: AsyncSession, email: str, code: str, *, now: datetime | None = None) -> tuple[str, User | None, PasswordResetChallenge | None]:
    """Compare a code with the account's current challenge. A wrong code
    counts as an attempt; at the limit the challenge locks."""
    now = now or _now()
    user = await _account(db, email)
    code = re.sub(r"\D", "", code or "")
    if user is None:
        return INVALID, None, None
    challenge = await _active(db, user.id)
    if challenge is None or _aware(challenge.expires_at) <= now:
        return INVALID, user, None
    limit = get_settings().PASSWORD_RESET_MAX_ATTEMPTS
    if challenge.attempts >= limit:
        return LOCKED, user, challenge
    if len(code) == CODE_DIGITS and hmac.compare_digest(_hash(code, challenge.salt), challenge.code_hash):
        return VALID, user, challenge
    challenge.attempts += 1
    await db.commit()
    return (LOCKED if challenge.attempts >= limit else INVALID), user, challenge


def _raise_for(outcome: str) -> None:
    if outcome == LOCKED:
        raise ResetError("Too many incorrect codes. Request a new code to try again.")
    if outcome != VALID:
        raise ResetError("Invalid or expired code.")


async def verify(db: AsyncSession, email: str, code: str) -> None:
    outcome, _, _ = await check_code(db, email, code)
    _raise_for(outcome)


async def reset(db: AsyncSession, email: str, code: str, password: str, *, set_password=None) -> User:
    """Spend the code and set the new password. Returns the user."""
    if not PASSWORD_RE.match(password or ""):
        raise ResetError(PASSWORD_RULE)
    outcome, user, challenge = await check_code(db, email, code)
    _raise_for(outcome)
    # Spend the code before the credential changes: single-use holds even if
    # setting the password fails below (the person then requests a new code).
    challenge.consumed_at = _now()
    await db.commit()
    try:
        (set_password or supabase_admin.set_password)(user.id, password)
    except supabase_admin.PasswordRejectedError as exc:
        # Nothing changed: give the code back so the person can pick another
        # password without requesting a new code.
        challenge.consumed_at = None
        await db.commit()
        raise ResetError(str(exc)) from exc
    return user
