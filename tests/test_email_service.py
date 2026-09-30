from email_service import (
    SMTPEmailProvider,
    send_password_reset_email,
    send_verification_email,
)


def test_console_provider_prints_verification_message(capsys):
    result = send_verification_email(
        'owner@example.test',
        'http://127.0.0.1:5000/verify-email/test-token',
        {},
    )

    output = capsys.readouterr().out
    assert result.status == 'sent'
    assert result.mode == 'console'
    assert 'Kitchen Factory Lite - Verify Your Email Address' in output
    assert 'Thank you for registering your company' in output
    assert 'http://127.0.0.1:5000/verify-email/test-token' in output


def test_smtp_provider_sends_message(monkeypatch):
    class FakeSMTP:
        def __init__(self, host, port, **kwargs):
            self.host = host
            self.port = port
            self.messages = []
            self.logged_in = None
            self.started_tls = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def ehlo(self):
            pass

        def starttls(self, **kwargs):
            self.started_tls = True

        def login(self, username, password):
            self.logged_in = (username, password)

        def send_message(self, message):
            self.messages.append(message)

    smtp_clients = []

    def create_smtp(host, port, **kwargs):
        client = FakeSMTP(host, port, **kwargs)
        smtp_clients.append(client)
        return client

    monkeypatch.setattr('email_service.smtplib.SMTP', create_smtp)
    monkeypatch.setenv('KITCHEN_FACTORY_EMAIL_PROVIDER', 'smtp')
    result = send_verification_email(
        'owner@example.test',
        'https://kitchen.example/verify-email/test-token',
        {
            'smtp_server': 'smtp.example.test',
            'smtp_port': '587',
            'smtp_username': 'smtp-user',
            'smtp_password': 'smtp-secret',
            'sender_email': 'noreply@example.test',
        },
    )

    assert result.status == 'sent'
    assert result.mode == 'smtp'
    assert smtp_clients[0].started_tls
    assert smtp_clients[0].logged_in == ('smtp-user', 'smtp-secret')
    assert smtp_clients[0].messages[0]['To'] == 'owner@example.test'
    assert smtp_clients[0].messages[0]['Subject'] == (
        'Kitchen Factory Lite - Verify Your Email Address'
    )
    assert 'https://kitchen.example/verify-email/test-token' in (
        smtp_clients[0].messages[0].get_content()
    )


def test_smtp_provider_reports_delivery_failure(monkeypatch):
    def fail_connect(*args, **kwargs):
        raise OSError('SMTP is unavailable.')

    monkeypatch.setattr('email_service.smtplib.SMTP', fail_connect)
    result = SMTPEmailProvider({
        'smtp_server': 'smtp.example.test',
        'smtp_port': '587',
        'sender_email': 'noreply@example.test',
    }).send('owner@example.test', 'subject', 'body')

    assert result.status == 'failed'
    assert result.error_type == 'OSError'


def test_password_reset_uses_email_provider(monkeypatch):
    monkeypatch.setenv('KITCHEN_FACTORY_EMAIL_PROVIDER', 'smtp')
    monkeypatch.setattr(
        'email_service.smtplib.SMTP',
        lambda *args, **kwargs: type('SMTPFailure', (), {
            '__enter__': lambda self: self,
            '__exit__': lambda self, *exc: False,
            'ehlo': lambda self: None,
            'starttls': lambda self, **kwargs: None,
            'send_message': lambda self, message: setattr(self, 'message', message),
        })(),
    )

    result = send_password_reset_email(
        'owner@example.test',
        'https://kitchen.example/reset-password/test-token',
        {
            'smtp_server': 'smtp.example.test',
            'smtp_port': '587',
            'sender_email': 'noreply@example.test',
        },
    )

    assert result.status == 'sent'
