"""Transactional email delivery through Resend or the local console."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Protocol

import requests


logger = logging.getLogger(__name__)
RESEND_EMAILS_URL = 'https://api.resend.com/emails'
SENDER = 'Kitchen Factory Lite <onboarding@resend.dev>'


@dataclass(frozen=True)
class EmailSendResult:
    status: str
    mode: str
    error_type: str | None = None


class EmailProvider(Protocol):
    mode: str

    def send(self, recipient: str, subject: str, body: str) -> EmailSendResult:
        ...


class ConsoleEmailProvider:
    mode = 'console'

    def send(self, recipient: str, subject: str, body: str) -> EmailSendResult:
        print(f'\nEmail to: {recipient}\nSubject: {subject}\n\n{body}\n')
        return EmailSendResult('sent', self.mode)


class ResendEmailProvider:
    mode = 'resend'

    def __init__(self, api_key: str):
        self.api_key = api_key

    def send(self, recipient: str, subject: str, body: str) -> EmailSendResult:
        try:
            response = requests.post(
                RESEND_EMAILS_URL,
                headers={
                    'Authorization': f'Bearer {self.api_key}',
                    'Content-Type': 'application/json',
                },
                json={
                    'from': SENDER,
                    'to': [recipient],
                    'subject': subject,
                    'text': body,
                },
                timeout=15,
            )
            if not response.ok:
                logger.error(
                    'Resend email delivery failed: HTTP %s: %s',
                    response.status_code,
                    response.text,
                )
                return EmailSendResult('failed', self.mode, 'ResendAPIError')
            return EmailSendResult('sent', self.mode)
        except requests.RequestException as exc:
            logger.exception('Resend email delivery failed: %s', exc)
            return EmailSendResult('failed', self.mode, type(exc).__name__)


def _provider():
    api_key = os.environ.get('RESEND_API_KEY', '').strip()

    logger.info(
        "RESEND_API_KEY present: %s, starts with: %s",
        bool(api_key),
        api_key[:6] if api_key else "NONE"
    )

    if api_key:
        return ResendEmailProvider(api_key)
    production = (
        os.environ.get('KITCHEN_FACTORY_ENV', '').strip().lower() == 'production'
        or bool(os.environ.get('PORT'))
    )
    if not production:
        return ConsoleEmailProvider()
    logger.error('Resend email delivery is not configured; RESEND_API_KEY is missing.')
    return None


def _send(recipient, subject, body):
    provider = _provider()
    if provider is None:
        return EmailSendResult('failed', 'not_configured', 'ResendAPIKeyMissing')
    return provider.send(recipient, subject, body)


def send_verification_email(recipient, verification_link):
    body = (
        'Hello,\n\n'
        'Thank you for registering your company with Kitchen Factory Lite.\n\n'
        'Please verify your email address by clicking the link below:\n\n'
        f'{verification_link}\n\n'
        'If you did not create this account, please ignore this email.\n\n'
        'Regards\n'
        'Kitchen Factory Lite'
    )
    result = _send(
        recipient,
        'Kitchen Factory Lite - Verify Your Email Address',
        body,
    )
    if result.status == 'failed':
        logger.error('Verification URL for failed email delivery: %s', verification_link)
    return result


def send_password_reset_email(recipient, reset_link):
    body = (
        'Hello,\n\n'
        'A password reset was requested for your Kitchen Factory Lite account.\n\n'
        f'Reset your password using this link:\n\n{reset_link}\n\n'
        'This link expires in one hour and can only be used once. '
        'If you did not request this reset, you can ignore this email.\n\n'
        'Regards\n'
        'Kitchen Factory Lite'
    )
    return _send(
        recipient,
        'Kitchen Factory Lite - Password Reset',
        body,
    )
