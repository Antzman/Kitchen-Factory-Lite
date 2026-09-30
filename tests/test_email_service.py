import requests

from email_service import (
    RESEND_EMAILS_URL,
    ResendEmailProvider,
    send_password_reset_email,
    send_verification_email,
)


class FakeResponse:
    def __init__(self, status_code=200, text='{"id":"email-id"}'):
        self.status_code = status_code
        self.text = text
        self.ok = 200 <= status_code < 400


def test_console_provider_prints_verification_message(capsys, monkeypatch):
    monkeypatch.delenv('RESEND_API_KEY', raising=False)
    monkeypatch.delenv('PORT', raising=False)
    monkeypatch.delenv('KITCHEN_FACTORY_ENV', raising=False)
    result = send_verification_email(
        'owner@example.test',
        'http://127.0.0.1:5000/verify-email/test-token',
    )

    output = capsys.readouterr().out
    assert result.status == 'sent'
    assert result.mode == 'console'
    assert 'Kitchen Factory Lite - Verify Your Email Address' in output
    assert 'Thank you for registering your company' in output
    assert 'http://127.0.0.1:5000/verify-email/test-token' in output


def test_resend_provider_posts_required_message(monkeypatch):
    monkeypatch.setenv('RESEND_API_KEY', 'test-api-key')
    sent = {}

    def fake_post(url, **kwargs):
        sent['url'] = url
        sent.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr('email_service.requests.post', fake_post)
    result = send_verification_email(
        'owner@example.test',
        'https://kitchen.example/verify-email/test-token',
    )

    assert result.status == 'sent'
    assert result.mode == 'resend'
    assert sent['url'] == RESEND_EMAILS_URL
    assert sent['headers']['Authorization'] == 'Bearer test-api-key'
    assert sent['json']['from'] == 'Kitchen Factory Lite <onboarding@resend.dev>'
    assert sent['json']['to'] == ['owner@example.test']
    assert sent['json']['subject'] == 'Kitchen Factory Lite - Verify Your Email Address'
    assert 'https://kitchen.example/verify-email/test-token' in sent['json']['text']
    assert sent['timeout'] == 15


def test_resend_provider_logs_full_http_error(monkeypatch, caplog):
    provider = ResendEmailProvider('test-api-key')

    class ErrorResponse(FakeResponse):
        def __init__(self):
            super().__init__(422, '{"message":"Recipient is invalid","name":"validation_error"}')

    monkeypatch.setattr(
        'email_service.requests.post',
        lambda *args, **kwargs: ErrorResponse(),
    )
    result = provider.send('invalid@example.test', 'subject', 'body')

    assert result.status == 'failed'
    assert result.error_type == 'ResendAPIError'
    assert 'HTTP 422' in caplog.text
    assert 'Recipient is invalid' in caplog.text


def test_resend_provider_logs_exception_and_verification_url(monkeypatch, caplog):
    monkeypatch.setenv('RESEND_API_KEY', 'test-api-key')

    def fail_request(*args, **kwargs):
        raise requests.ConnectionError('Resend API is unavailable.')

    monkeypatch.setattr('email_service.requests.post', fail_request)
    verification_url = 'https://kitchen.example/verify-email/test-token'
    result = send_verification_email('owner@example.test', verification_url)

    assert result.status == 'failed'
    assert result.error_type == 'ConnectionError'
    assert 'Resend API is unavailable.' in caplog.text
    assert verification_url in caplog.text


def test_password_reset_uses_resend(monkeypatch):
    monkeypatch.setenv('RESEND_API_KEY', 'test-api-key')
    sent = {}

    def fake_post(url, **kwargs):
        sent.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr('email_service.requests.post', fake_post)
    result = send_password_reset_email(
        'owner@example.test',
        'https://kitchen.example/reset-password/test-token',
    )

    assert result.status == 'sent'
    assert sent['json']['from'] == 'Kitchen Factory Lite <onboarding@resend.dev>'
    assert 'https://kitchen.example/reset-password/test-token' in sent['json']['text']
