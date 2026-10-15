"""ZoikoLogia account emails, styled like the app's sign-in screens: light
page, white card, the ZoikoLogia mark (teal tile, white frame, three gold
bars), dark ink button, teal accents.

Email clients ignore <style> blocks and strip SVG, so everything is inline
styles and tables, and the mark is drawn in HTML. Every value placed in the
HTML is escaped. Each email has a plain-text alternative.
"""
from __future__ import annotations

from html import escape

INK, MUTED, LINE, SOFT, BRAND, PAGE = "#151922", "#637083", "#d8dde5", "#eef1f5", "#0b5f7a", "#f7f8fa"

_MARK = (
    '<td width="40" height="40" align="center" valign="middle" '
    'style="width:40px;height:40px;background-color:#16799a;border-radius:11px;">'
    '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border:3px solid #ffffff;border-radius:2px;">'
    '<tr><td style="padding:3px 3px 3px 4px;line-height:0;font-size:0;">'
    '<span style="display:inline-block;width:4px;height:12px;background-color:#f3c437;margin-right:2px;"></span>'
    '<span style="display:inline-block;width:4px;height:12px;background-color:#f3c437;margin-right:2px;"></span>'
    '<span style="display:inline-block;width:4px;height:12px;background-color:#f3c437;"></span>'
    "</td></tr></table></td>"
)


def _layout(preheader: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light"><title>ZoikoLogia</title></head>
<body style="margin:0;padding:0;background-color:{PAGE};font-family:Inter,'Segoe UI',Helvetica,Arial,sans-serif;color:{INK};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{escape(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{PAGE};">
<tr><td align="center" style="padding:40px 16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:480px;background-color:#ffffff;border:1px solid {LINE};border-radius:16px;">
<tr><td style="padding:28px 28px 0 28px;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>{_MARK}
<td style="padding-left:12px;"><div style="font-size:15px;font-weight:700;color:{INK};line-height:1.2;">ZoikoLogia</div>
<div style="font-size:12px;color:{MUTED};line-height:1.4;">Governance intelligence workspace</div></td></tr></table>
</td></tr>
{body}
</table>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:480px;">
<tr><td align="center" style="padding:18px 12px 0 12px;font-size:11px;line-height:1.6;color:#8b96a3;">
ZoikoLogia&trade; with Kriton&trade; &middot; Automated security message, replies are not monitored.</td></tr></table>
</td></tr></table></body></html>"""


def _notice(title: str, text: str) -> str:
    return (f'<tr><td style="padding:20px 28px 0 28px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="border:1px solid rgba(11,95,122,0.2);background-color:#e9f2f5;border-radius:10px;"><tr>'
            f'<td style="padding:12px 16px;font-size:13px;line-height:1.6;color:{INK};"><strong style="color:{BRAND};">{escape(title)}</strong> '
            f"{escape(text)}</td></tr></table></td></tr>")


def password_reset_code(*, email: str, code: str, ttl_minutes: int, reset_url: str) -> tuple[str, str, str]:
    """(subject, html, text) for the 6-digit reset code."""
    spaced = " ".join(code)
    body = f"""
<tr><td style="padding:24px 28px 0 28px;">
<h1 style="margin:0;font-size:22px;line-height:1.3;font-weight:700;color:{INK};">Reset your password</h1>
<p style="margin:10px 0 0 0;font-size:14px;line-height:1.65;color:{MUTED};">We received a request to reset the password for
<span style="color:{INK};font-weight:600;">{escape(email)}</span>. Enter this code on the reset page, then choose and confirm your new password.</p>
</td></tr>
<tr><td style="padding:22px 28px 0 28px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{SOFT};border-radius:12px;">
<tr><td align="center" style="padding:18px 12px;">
<div style="font-size:11px;font-weight:700;letter-spacing:0.6px;text-transform:uppercase;color:{MUTED};">Your verification code</div>
<div style="margin-top:8px;font-family:'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace;font-size:32px;font-weight:700;letter-spacing:6px;color:{INK};">{escape(spaced)}</div>
<div style="margin-top:6px;font-size:12px;color:{MUTED};">Expires in {ttl_minutes} minutes &middot; works once</div>
</td></tr></table></td></tr>
<tr><td style="padding:20px 28px 0 28px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
<tr><td align="center" style="background-color:{INK};border-radius:10px;">
<a href="{escape(reset_url, quote=True)}" target="_blank" style="display:block;padding:12px 20px;font-size:14px;font-weight:700;color:#ffffff;text-decoration:none;border-radius:10px;">Open the reset page</a>
</td></tr></table></td></tr>
<tr><td style="padding:20px 28px 0 28px;font-size:13px;line-height:1.7;color:{INK};">
<div style="font-size:11px;font-weight:700;letter-spacing:0.6px;text-transform:uppercase;color:{MUTED};margin-bottom:4px;">Your new password needs</div>
<span style="color:{BRAND};">&#10003;</span>&nbsp;At least 8 characters<br>
<span style="color:{BRAND};">&#10003;</span>&nbsp;An uppercase and a lowercase letter<br>
<span style="color:{BRAND};">&#10003;</span>&nbsp;A number</td></tr>
{_notice("Didn't ask for this?", "Ignore this email and your password stays the same. Never share this code: ZoikoLogia will never ask you for it.")}
<tr><td style="padding:20px 28px 28px 28px;font-size:12px;line-height:1.6;color:{MUTED};">
Too many wrong attempts lock the code; you can then request a new one from the sign-in page.</td></tr>"""
    text = (f"Reset your ZoikoLogia password\n\nYour verification code: {code}\n"
            f"It expires in {ttl_minutes} minutes and works once.\n\nEnter it at: {reset_url}\n\n"
            "Didn't ask for this? Ignore this email and your password stays the same. Never share this code.\n")
    # The code stays out of the subject and preheader: both show in inbox
    # lists and lock-screen notifications.
    return ("Your ZoikoLogia password reset code",
            _layout(f"Your verification code expires in {ttl_minutes} minutes.", body), text)


def password_changed(*, email: str, changed_at: str, sign_in_url: str) -> tuple[str, str, str]:
    """(subject, html, text) confirming the password was changed."""
    body = f"""
<tr><td style="padding:24px 28px 0 28px;">
<h1 style="margin:0;font-size:22px;line-height:1.3;font-weight:700;color:{INK};">Your password was changed</h1>
<p style="margin:10px 0 0 0;font-size:14px;line-height:1.65;color:{MUTED};">The password for
<span style="color:{INK};font-weight:600;">{escape(email)}</span> was changed on {escape(changed_at)}.
For your security, you were signed out on every device.</p></td></tr>
<tr><td style="padding:22px 28px 0 28px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
<tr><td align="center" style="background-color:{INK};border-radius:10px;">
<a href="{escape(sign_in_url, quote=True)}" target="_blank" style="display:block;padding:12px 20px;font-size:14px;font-weight:700;color:#ffffff;text-decoration:none;border-radius:10px;">Sign in</a>
</td></tr></table></td></tr>
{_notice("Wasn't you?", "Reset your password again right away and contact your ZoikoLogia administrator.")}
<tr><td style="padding:0 0 28px 0;"></td></tr>"""
    text = (f"Your ZoikoLogia password was changed\n\nThe password for {email} was changed on {changed_at}. "
            f"You were signed out on every device.\n\nSign in: {sign_in_url}\n\n"
            "Wasn't you? Reset your password again right away and contact your administrator.\n")
    return "Your ZoikoLogia password was changed", _layout("Your password was changed.", body), text
