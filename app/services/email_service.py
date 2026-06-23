"""Transactional email via SMTP."""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings

logger = logging.getLogger(__name__)


def _smtp_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_FROM_EMAIL)


def send_email(*, to_email: str, subject: str, html_body: str, text_body: str | None = None) -> bool:
    if not _smtp_configured():
        logger.warning("SMTP not configured — email not sent to %s: %s", to_email, subject)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    msg["To"] = to_email

    recipients = [to_email]
    if settings.SMTP_BCC_SELF and settings.SMTP_FROM_EMAIL:
        msg["Bcc"] = settings.SMTP_FROM_EMAIL
        if settings.SMTP_FROM_EMAIL not in recipients:
            recipients.append(settings.SMTP_FROM_EMAIL)

    plain = text_body or html_body
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as server:
            if settings.SMTP_USE_TLS:
                server.starttls()
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM_EMAIL, recipients, msg.as_string())
        return True
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", to_email, exc)
        return False


def send_verification_email(to_email: str, username: str, token: str) -> bool:
    link = f"{settings.FRONTEND_URL.rstrip('/')}/verify-email?token={token}"
    subject = "Verify your Tradin account"
    html = f"""
    <p>Hi {username},</p>
    <p>Welcome to Tradin! Click the link below to verify your email address:</p>
    <p><a href="{link}">{link}</a></p>
    <p>This link expires in 24 hours.</p>
    """
    return send_email(to_email=to_email, subject=subject, html_body=html)


def send_password_reset_email(to_email: str, username: str, token: str) -> bool:
    link = f"{settings.FRONTEND_URL.rstrip('/')}/reset-password?token={token}"
    subject = "Reset your Tradin password"
    html = f"""
    <p>Hi {username},</p>
    <p>We received a request to reset your password. Click the link below:</p>
    <p><a href="{link}">{link}</a></p>
    <p>If you did not request this, you can ignore this email. The link expires in 1 hour.</p>
    """
    return send_email(to_email=to_email, subject=subject, html_body=html)
