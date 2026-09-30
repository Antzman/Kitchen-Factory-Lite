"""Provider-neutral transactional email delivery."""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol


logger = logging.getLogger(__name__)


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


class SMTPEmailProvider:
    mode = 'smtp'

    def __init__(self, configuration):
        self.configuration = configuration

    def send(self, recipient: str, subject: str, body: str) -> EmailSendResult:
        config = self.configuration
        sender_name = config.get('sender_display_name') or 'Kitchen Factory Lite'
        sender_email = config['sender_email']
        message = EmailMessage()
        message['Subject'] = subject
        message['From'] = f'{sender_name} <{sender_email}>'
        message['To'] = recipient
        message.set_content(body)

        try:
            host = config['smtp_server']
            port = int(config.get('smtp_port') or 587)
            if port == 465:
                client = smtplib.SMTP_SSL(
                    host, port, timeout=15, context=ssl.create_default_context()
                )
            else:
                client = smtplib.SMTP(host, port, timeout=15)
            with client:
                if port != 465:
                    client.ehlo()
                    client.starttls(context=ssl.create_default_context())
                    client.ehlo()
                username = config.get('smtp_username') or ''
                password = config.get('smtp_password') or ''
                if username:
                    client.login(username, password)
                client.send_message(message)
            return EmailSendResult('sent', self.mode)
        except (smtplib.SMTPException, OSError, ssl.SSLError, ValueError) as exc:
            logger.exception("SMTP email delivery failed")
            return EmailSendResult('failed', self.mode, type(exc).__name__)


def _configuration_with_environment(configuration):
    resolved = dict(configuration)
    environment_names = {
        'smtp_server': 'KITCHEN_FACTORY_SMTP_SERVER',
        'smtp_port': 'KITCHEN_FACTORY_SMTP_PORT',
        'smtp_username': 'KITCHEN_FACTORY_SMTP_USERNAME',
        'smtp_password': 'KITCHEN_FACTORY_SMTP_PASSWORD',
        'sender_email': 'KITCHEN_FACTORY_SENDER_EMAIL',
        'sender_display_name': 'KITCHEN_FACTORY_SENDER_NAME',
    }
    for key, environment_name in environment_names.items():
        configured = os.environ.get(environment_name)
        if configured:
            resolved[key] = configured
    return resolved


def _provider(configuration):
    provider_name = os.environ.get('KITCHEN_FACTORY_EMAIL_PROVIDER', '').strip().lower()
    resolved = _configuration_with_environment(configuration)
    smtp_ready = bool(resolved.get('smtp_server') and resolved.get('sender_email'))
    production = (
        os.environ.get('KITCHEN_FACTORY_ENV', '').strip().lower() == 'production'
        or bool(os.environ.get('PORT'))
    )

    if provider_name:
        if provider_name == 'smtp' and smtp_ready:
            return SMTPEmailProvider(resolved)
        logger.error('Email provider "%s" is unsupported or incompletely configured.', provider_name)
        return None, 'not_configured'
    if smtp_ready:
        return SMTPEmailProvider(resolved)
    if not production:
        return ConsoleEmailProvider()
    logger.error('Transactional email delivery is not configured in production.')
    return None, 'not_configured'


def _send(recipient, subject, body, configuration):
    provider = _provider(configuration)
    if isinstance(provider, tuple):
        return EmailSendResult('failed', provider[1], 'EmailProviderNotConfigured')
    return provider.send(recipient, subject, body)


def send_verification_email(recipient, verification_link, configuration):
    body = (
        'Hello,\n\n'
        'Thank you for registering your company with Kitchen Factory Lite.\n\n'
        'Please verify your email address by clicking the link below:\n\n'
        f'{verification_link}\n\n'
        'If you did not create this account, please ignore this email.\n\n'
        'Regards\n'
        'Kitchen Factory Lite'
    )
    return _send(
        recipient,
        'Kitchen Factory Lite - Verify Your Email Address',
        body,
        configuration,
    )


def send_password_reset_email(recipient, reset_link, configuration):
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
        configuration,
    )
