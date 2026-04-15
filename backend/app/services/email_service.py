from __future__ import annotations

import json
import logging
import smtplib
from email.mime.text import MIMEText
from typing import Optional
from urllib import error, request

from sqlmodel import Session

from backend.app.core.config import settings
from backend.app.models import Notification


logger = logging.getLogger(__name__)


class EmailService:
    @staticmethod
    def send_email(
        to: str,
        subject: str,
        body: str,
        *,
        session: Optional[Session] = None,
        employee_id: int | None = None,
        notification_type: str = "general",
    ) -> bool:
        try:
            if settings.sendgrid_api_key.strip():
                EmailService._send_via_sendgrid(to=to, subject=subject, body=body)
            else:
                EmailService._send_via_smtp(to=to, subject=subject, body=body)
        except Exception:
            logger.exception("EmailService failed for recipient=%s subject=%s", to, subject)
            EmailService._log_notification(
                session=session,
                employee_id=employee_id,
                notification_type=notification_type,
                subject=subject,
                body=body,
                to_email=to,
                status="failed",
            )
            return False

        EmailService._log_notification(
            session=session,
            employee_id=employee_id,
            notification_type=notification_type,
            subject=subject,
            body=body,
            to_email=to,
            status="sent",
        )
        return True

    @staticmethod
    def _send_via_sendgrid(*, to: str, subject: str, body: str) -> None:
        payload = {
            "personalizations": [{"to": [{"email": to}]}],
            "from": {
                "email": settings.email_from_address,
                "name": settings.email_from_name,
            },
            "subject": subject,
            "content": [{"type": "text/plain", "value": body}],
        }
        http_request = request.Request(
            "https://api.sendgrid.com/v3/mail/send",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.sendgrid_api_key.strip()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=30) as response:
                if response.status not in {200, 202}:
                    raise RuntimeError(f"Unexpected SendGrid response status: {response.status}")
        except error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"SendGrid request failed with status {exc.code}: {body_text}") from exc

    @staticmethod
    def _send_via_smtp(*, to: str, subject: str, body: str) -> None:
        if not settings.smtp_host.strip() or not settings.smtp_user.strip() or not settings.smtp_pass.strip():
            raise RuntimeError("SMTP is not fully configured. Set SMTP_HOST, SMTP_USER, and SMTP_PASS.")

        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = f"{settings.email_from_name} <{settings.email_from_address}>"
        msg["To"] = to

        with smtplib.SMTP(settings.smtp_host.strip(), settings.smtp_port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(settings.smtp_user.strip(), settings.smtp_pass.strip())
            smtp.sendmail(settings.email_from_address, [to], msg.as_string())

    @staticmethod
    def _log_notification(
        *,
        session: Optional[Session],
        employee_id: int | None,
        notification_type: str,
        subject: str,
        body: str,
        to_email: str,
        status: str,
    ) -> None:
        if session is None:
            return

        try:
            notification = Notification(
                employee_id=employee_id,
                notification_type=notification_type,
                subject=subject,
                body=body,
                sent_to_email=to_email,
                status=status,
            )
            session.add(notification)
            session.commit()
        except Exception:
            logger.exception("Failed to record notification log for recipient=%s", to_email)
            session.rollback()
