"""Transactional email through Resend's HTTP API.

Best effort by design: a mail outage must never break the request that
triggered it, so failures are logged and reported as False rather than
raised. Callers that must know (a security email the user is waiting for)
check the return value.
"""
from __future__ import annotations

import logging

import httpx

from app.core.config import get_settings

log = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


def _mask(address: str) -> str:
    """Log an address without writing it in full."""
    name, _, domain = address.partition("@")
    return f"{name[:2]}***@{domain}" if domain else "***"


def send_email(to: str, subject: str, html: str, text: str | None = None) -> bool:
    settings = get_settings()
    if not settings.RESEND_API_KEY:
        log.warning("RESEND_API_KEY not set; email to %s not sent (%s)", _mask(to), subject)
        return False
    payload = {"from": settings.MAIL_FROM, "to": [to], "subject": subject, "html": html}
    if text:
        payload["text"] = text
    try:
        response = httpx.post(RESEND_URL, json=payload, timeout=10,
                              headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"})
        if response.status_code >= 400:
            # Resend explains the refusal in the body (unverified sender domain,
            # testing-mode recipient, rate limit); keep it for diagnosis.
            log.error("Email to %s refused: HTTP %s %s", _mask(to), response.status_code, response.text[:300])
            return False
        return True
    except httpx.HTTPError as exc:
        log.error("Email to %s failed: %s", _mask(to), type(exc).__name__)
        return False
