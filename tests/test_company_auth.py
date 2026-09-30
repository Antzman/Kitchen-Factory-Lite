import sqlite3
import re

import db
from db import clear_tenant_context, set_tenant_context
from services import (
    authenticate_user,
    create_bulk_portioning,
    create_email_verification_token,
    create_manufacturing_transaction,
    create_password_reset_token,
    create_stock_item,
    list_manufacturing_history,
    list_recent_portioning,
    register_company,
    reset_password,
    update_user,
    verify_email_token,
    get_email_settings,
    update_email_settings,
)
from werkzeug.security import check_password_hash


def test_registration_password_hash_login_and_single_use_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'auth-test.db')
    db.init_db()
    user = register_company(
        'Test Kitchen', 'owner@example.test',
        'correct-horse-battery-123', 'correct-horse-battery-123',
    )

    assert user['role'] == 'Company Administrator'
    assert check_password_hash(user['password_hash'], 'correct-horse-battery-123')
    assert authenticate_user('owner@example.test', 'incorrect-password') is None
    assert authenticate_user('owner@example.test', 'correct-horse-battery-123') is None
    assert verify_email_token(user['verification_token']) == ('verified', user['id'])
    assert authenticate_user('owner@example.test', 'correct-horse-battery-123')['id'] == user['id']
    assert verify_email_token(user['verification_token'])[0] == 'invalid'

    token = create_password_reset_token('owner@example.test')
    assert token
    reset_password(token, 'brand-new-password-456', 'brand-new-password-456')
    assert authenticate_user('owner@example.test', 'brand-new-password-456')['id'] == user['id']
    try:
        reset_password(token, 'third-password-789', 'third-password-789')
    except ValueError as exc:
        assert 'invalid or has expired' in str(exc)
    else:
        raise AssertionError('A reset token must not be reusable.')
    expired_token = create_password_reset_token('owner@example.test')
    conn = db.get_db_connection()
    conn.execute(
        'UPDATE password_reset_tokens SET expires_at = ? WHERE user_id = ? AND used_at IS NULL',
        ('2000-01-01T00:00:00', user['id']),
    )
    conn.commit()
    conn.close()
    try:
        reset_password(
            expired_token, 'expired-token-password-123', 'expired-token-password-123'
        )
    except ValueError as exc:
        assert 'invalid or has expired' in str(exc)
    else:
        raise AssertionError('An expired reset token must be rejected.')

    set_tenant_context(user['company_id'], user['id'])
    conn = db.get_db_connection()
    try:
        actions = {
            row['action'] for row in conn.execute(
                'SELECT action FROM audit_log WHERE company_id = ?',
                (user['company_id'],),
            )
        }
        assert {'COMPANY REGISTERED', 'PASSWORD RESET'} <= actions
    finally:
        conn.close()
        clear_tenant_context()


def test_local_registration_verification_login_and_logout_routes(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'web-auth-test.db')
    from app import create_app

    application = create_app()
    application.testing = True
    client = application.test_client()

    assert client.get('/register').status_code == 200
    with client.session_transaction() as session:
        csrf_token = session['csrf_token']
    assert client.post('/register', data={'company_name': 'CSRF rejection'}).status_code == 302
    response = client.post(
        '/register',
        data={
            'csrf_token': csrf_token,
            'company_name': 'Local Test Kitchen',
            'email': 'local-owner@example.test',
            'password': 'local-registration-password-123',
            'confirm_password': 'local-registration-password-123',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b'Company registered. Verify your email address before signing in.' in response.data
    assert b'Verification link: http://localhost/verify-email/' in response.data
    initial_token = re.search(
        rb'/verify-email/([A-Za-z0-9_-]+)', response.data,
    ).group(1).decode()

    with client.session_transaction() as session:
        csrf_token = session['csrf_token']
    resend_response = client.post(
        '/resend-verification',
        data={'csrf_token': csrf_token, 'email': 'local-owner@example.test'},
        follow_redirects=True,
    )
    assert b'If an active, unverified account exists' in resend_response.data
    verification_token = re.search(
        rb'/verify-email/([A-Za-z0-9_-]+)', resend_response.data,
    ).group(1).decode()
    assert verification_token != initial_token
    assert client.get(f'/verify-email/{initial_token}', follow_redirects=True).status_code == 200

    assert client.get('/login').status_code == 200
    with client.session_transaction() as session:
        csrf_token = session['csrf_token']
    response = client.post(
        '/login',
        data={
            'csrf_token': csrf_token,
            'email': 'local-owner@example.test',
            'password': 'local-registration-password-123',
        },
        follow_redirects=True,
    )
    assert b'Please verify your email address before signing in.' in response.data

    verified_response = client.get(
        f'/verify-email/{verification_token}', follow_redirects=True,
    )
    assert b'Email verified successfully. You can now sign in.' in verified_response.data
    assert client.get('/dashboard').status_code == 302

    assert client.get('/login').status_code == 200
    with client.session_transaction() as session:
        csrf_token = session['csrf_token']
    response = client.post(
        '/login',
        data={
            'csrf_token': csrf_token,
            'email': 'local-owner@example.test',
            'password': 'local-registration-password-123',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b'Logged in successfully.' in response.data
    assert client.get('/dashboard').status_code == 200

    with client.session_transaction() as session:
        csrf_token = session['csrf_token']
    assert client.post('/logout', data={'csrf_token': csrf_token}).status_code == 302
    assert client.get('/dashboard').status_code == 302

    assert client.get('/login').status_code == 200
    with client.session_transaction() as session:
        csrf_token = session['csrf_token']
    response = client.post(
        '/login',
        data={
            'csrf_token': csrf_token,
            'email': 'local-owner@example.test',
            'password': 'local-registration-password-123',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b'Logged in successfully.' in response.data
    assert client.get('/users').status_code == 200
    with client.session_transaction() as session:
        owner_id = session['user_id']
        company_id = session['company_id']
        csrf_token = session['csrf_token']
    response = client.post(
        '/users',
        data={
            'csrf_token': csrf_token,
            'display_name': 'Kitchen Manager',
            'email': 'manager@example.test',
            'role': 'Manager',
            'password': 'manager-account-password-123',
            'confirm_password': 'manager-account-password-123',
            'active': '1',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    conn = db.get_db_connection()
    manager = conn.execute(
        'SELECT id FROM users WHERE company_id = ? AND email = ?',
        (company_id, 'manager@example.test'),
    ).fetchone()
    conn.close()
    assert manager

    assert client.post(
        f'/users/{manager["id"]}/reset-password',
        data={
            'csrf_token': csrf_token,
            'password': 'manager-reset-password-456',
            'confirm_password': 'manager-reset-password-456',
        },
        follow_redirects=True,
    ).status_code == 200
    with client.session_transaction() as session:
        session['user_id'] = manager['id']
        session['company_id'] = company_id
        session['username'] = 'manager@example.test'
        session['csrf_token'] = csrf_token
    assert client.get('/users').status_code == 302
    with client.session_transaction() as session:
        session['user_id'] = owner_id
        session['company_id'] = company_id
        session['username'] = 'local-owner@example.test'
        session['csrf_token'] = csrf_token
    assert client.post(
        '/users',
        data={
            'csrf_token': csrf_token,
            'user_id': manager['id'],
            'display_name': 'Kitchen Manager',
            'email': 'manager@example.test',
            'role': 'Manager',
        },
        follow_redirects=True,
    ).status_code == 200
    assert authenticate_user('manager@example.test', 'manager-reset-password-456') is None


def test_expired_verification_token_is_invalidated_and_audited(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'expired-verification.db')
    db.init_db()
    user = register_company(
        'Expired Kitchen', 'expired@example.test',
        'expired-password-1234', 'expired-password-1234',
    )
    conn = db.get_db_connection()
    conn.execute(
        'UPDATE users SET verification_token_expiry = ? WHERE id = ?',
        ('2000-01-01T00:00:00', user['id']),
    )
    conn.commit()
    conn.close()

    assert verify_email_token(user['verification_token']) == ('expired', user['id'])
    assert verify_email_token(user['verification_token']) == ('invalid', None)
    conn = db.get_db_connection()
    try:
        updated = conn.execute(
            'SELECT email_verified, verification_token, verified_at FROM users WHERE id = ?',
            (user['id'],),
        ).fetchone()
        actions = {
            row['action'] for row in conn.execute(
                'SELECT action FROM audit_log WHERE company_id = ?',
                (user['company_id'],),
            )
        }
        assert updated['email_verified'] == 0
        assert updated['verification_token'] is None
        assert updated['verified_at'] is None
        assert {'VERIFICATION TOKEN EXPIRED', 'VERIFICATION FAILED'} <= actions
    finally:
        conn.close()


def test_existing_password_accounts_migrate_as_verified(tmp_path, monkeypatch):
    database_path = tmp_path / 'existing-users.db'
    monkeypatch.setattr(db, 'DB_PATH', database_path)
    conn = sqlite3.connect(database_path)
    conn.execute(
        '''CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            date_created TEXT NOT NULL,
            email TEXT,
            password_hash TEXT
        )'''
    )
    conn.execute(
        '''INSERT INTO users(username, display_name, role, date_created, email, password_hash)
           VALUES (?, ?, ?, ?, ?, ?)''',
        (
            'legacy-user',
            'Legacy User',
            'User',
            '2024-01-01T00:00:00',
            'legacy-user@example.test',
            'existing-hash',
        ),
    )
    conn.commit()
    conn.close()

    db.init_db()
    conn = db.get_db_connection()
    try:
        migrated = conn.execute(
            'SELECT email_verified FROM users WHERE username = ?',
            ('legacy-user',),
        ).fetchone()
        assert migrated['email_verified'] == 1
    finally:
        conn.close()


def test_production_registration_logs_email_failure_without_showing_link(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'production-email.db')
    monkeypatch.setenv('KITCHEN_FACTORY_ENV', 'production')
    monkeypatch.setenv('KITCHEN_FACTORY_EMAIL_PROVIDER', 'smtp')
    monkeypatch.setenv('KITCHEN_FACTORY_SMTP_SERVER', 'smtp.example.test')
    monkeypatch.setenv('KITCHEN_FACTORY_SENDER_EMAIL', 'noreply@example.test')

    def fail_connect(*args, **kwargs):
        raise OSError('SMTP server is unavailable.')

    monkeypatch.setattr('email_service.smtplib.SMTP', fail_connect)
    from app import create_app

    application = create_app()
    application.testing = True
    client = application.test_client()
    client.get('/register')
    with client.session_transaction() as session:
        csrf_token = session['csrf_token']
    response = client.post(
        '/register',
        data={
            'csrf_token': csrf_token,
            'company_name': 'Production Mail Kitchen',
            'email': 'production-mail@example.test',
            'password': 'production-mail-password-123',
            'confirm_password': 'production-mail-password-123',
        },
        follow_redirects=True,
    )

    assert b'could not send the verification email' in response.data
    assert b'Verification link:' not in response.data
    conn = db.get_db_connection()
    try:
        delivery = conn.execute(
            'SELECT status, error_type FROM email_delivery_log'
        ).fetchone()
        actions = {
            row['action'] for row in conn.execute(
                'SELECT action FROM audit_log',
            )
        }
        assert delivery['status'] == 'failed'
        assert delivery['error_type'] == 'OSError'
        assert 'VERIFICATION EMAIL FAILED' in actions
    finally:
        conn.close()


def test_changing_user_email_requires_new_verification(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'email-change.db')
    db.init_db()
    owner = register_company(
        'Email Change Kitchen', 'email-change-owner@example.test',
        'email-change-password-123', 'email-change-password-123',
    )
    token = create_email_verification_token(owner['id'])
    assert token
    verify_email_token(token)
    set_tenant_context(owner['company_id'], owner['id'])
    update_user(
        owner['id'], 'new-owner@example.test', owner['display_name'],
        owner['role'], True,
    )
    conn = db.get_db_connection()
    try:
        changed_user = conn.execute(
            'SELECT email_verified, verification_token, verified_at FROM users WHERE id = ?',
            (owner['id'],),
        ).fetchone()
        assert changed_user['email_verified'] == 0
        assert changed_user['verification_token'] is None
        assert changed_user['verified_at'] is None
    finally:
        conn.close()
    clear_tenant_context()


def test_legacy_data_migration_preserves_rows_and_foreign_keys(tmp_path, monkeypatch):
    database_path = tmp_path / 'legacy-test.db'
    monkeypatch.setattr(db, 'DB_PATH', database_path)
    conn = sqlite3.connect(database_path)
    conn.execute(
        '''CREATE TABLE categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT,
            created_by INTEGER,
            modified_at TEXT,
            modified_by INTEGER
        )'''
    )
    conn.execute(
        '''CREATE TABLE stock_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            item_type TEXT NOT NULL DEFAULT 'raw_material'
                CHECK(item_type IN ('raw_material','manufactured_item','portioned_item')),
            unit TEXT NOT NULL CHECK(unit IN ('kg','L','each')),
            quantity TEXT NOT NULL DEFAULT '0',
            category_id INTEGER,
            active INTEGER NOT NULL DEFAULT 1,
            date_created TEXT NOT NULL,
            date_modified TEXT NOT NULL,
            created_by INTEGER,
            modified_by INTEGER,
            unit_cost TEXT NOT NULL DEFAULT '0',
            notes TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(category_id) REFERENCES categories(id)
        )'''
    )
    conn.execute(
        '''CREATE TABLE menu_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            created_by INTEGER,
            modified_at TEXT NOT NULL,
            modified_by INTEGER,
            FOREIGN KEY(created_by) REFERENCES users(id),
            FOREIGN KEY(modified_by) REFERENCES users(id)
        )'''
    )
    conn.execute(
        '''CREATE TABLE menu_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE COLLATE NOCASE,
            name TEXT NOT NULL,
            item_type TEXT NOT NULL,
            category_id INTEGER NOT NULL,
            selling_price TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            date_created TEXT NOT NULL,
            date_modified TEXT NOT NULL,
            created_by INTEGER,
            modified_by INTEGER,
            FOREIGN KEY(category_id) REFERENCES menu_categories(id),
            FOREIGN KEY(created_by) REFERENCES users(id),
            FOREIGN KEY(modified_by) REFERENCES users(id)
        )'''
    )
    conn.execute(
        """INSERT INTO categories(id, name, description, active)
           VALUES (17, 'Legacy Bakery', 'Preserved category', 1)"""
    )
    conn.execute(
        """INSERT INTO stock_items
           (id, code, name, unit, quantity, category_id, date_created, date_modified, unit_cost)
           VALUES (23, 'LEGACY001', 'Legacy Flour', 'kg', '8.5', 17, '2024-01-01', '2024-01-01', '2.25')"""
    )
    conn.execute(
           """INSERT INTO menu_categories(id, name, created_at, modified_at)
              VALUES (31, 'Legacy Menu', '2024-01-01', '2024-01-01')"""
    )
    conn.execute(
           """INSERT INTO menu_items
              (id, code, name, item_type, category_id, selling_price, date_created, date_modified)
              VALUES (37, 'LEGACY-MENU', 'Legacy Menu Item', 'Ordinary Menu Item', 31,
                      '12.00', '2024-01-01', '2024-01-01')"""
    )
    conn.commit()
    conn.close()

    db.init_db()
    legacy = register_company(
        'Migrated Kitchen', 'migrated@example.test',
        'migration-password-123', 'migration-password-123',
    )
    conn = db.get_db_connection()
    try:
        category = conn.execute(
            'SELECT * FROM categories WHERE id = 17 AND company_id = ?',
            (legacy['company_id'],),
        ).fetchone()
        stock = conn.execute(
            'SELECT * FROM stock_items WHERE id = 23 AND company_id = ?',
            (legacy['company_id'],),
        ).fetchone()
        menu_category = conn.execute(
            'SELECT * FROM menu_categories WHERE id = 31 AND company_id = ?',
            (legacy['company_id'],),
        ).fetchone()
        menu_item = conn.execute(
            'SELECT * FROM menu_items WHERE id = 37 AND company_id = ?',
            (legacy['company_id'],),
        ).fetchone()
        violations = conn.execute('PRAGMA foreign_key_check').fetchall()
        assert category['name'] == 'Legacy Bakery'
        assert stock['code'] == 'LEGACY001'
        assert stock['category_id'] == category['id']
        assert menu_category['name'] == 'Legacy Menu'
        assert menu_item['code'] == 'LEGACY-MENU'
        assert menu_item['category_id'] == menu_category['id']
        assert not violations
    finally:
        conn.close()
    second = register_company(
        'Second Migrated Kitchen', 'second-migrated@example.test',
        'second-migration-password-123', 'second-migration-password-123',
    )
    set_tenant_context(second['company_id'], second['id'])
    conn = db.get_db_connection()
    try:
        second_category = conn.execute(
            "SELECT id FROM categories WHERE company_id = ? AND name = 'Prepared Foods'",
            (second['company_id'],),
        ).fetchone()['id']
    finally:
        conn.close()
    create_stock_item(
        'LEGACY001', 'Same Code in Separate Company', 'kg', '1',
        second_category, second['id'], '1.00',
    )
    clear_tenant_context()


def test_manufacturing_and_portioning_are_company_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'operations-test.db')
    db.init_db()
    owner = register_company(
        'Operations Kitchen', 'operations@example.test',
        'operations-password-123', 'operations-password-123',
    )
    set_tenant_context(owner['company_id'], owner['id'])
    conn = db.get_db_connection()
    category_id = conn.execute(
        "SELECT id FROM categories WHERE company_id = ? AND name = 'Prepared Foods'",
        (owner['company_id'],),
    ).fetchone()['id']
    conn.close()
    ingredient_id = create_stock_item(
        'RAW001', 'Raw Ingredient', 'kg', '10', category_id, owner['id'], '4.00'
    )
    output_id = create_stock_item(
        'MFG001', 'Manufactured Batch', 'kg', '0', category_id, owner['id'],
        '0.00', item_type='manufactured_item',
    )
    transaction = create_manufacturing_transaction(
        output_id, [{'item_id': ingredient_id, 'quantity': '2'}],
        '2', '1.5', owner['id'],
    )
    portion_source = create_stock_item(
        'PORTION-SOURCE', 'Portion Source', 'kg', '5', category_id, owner['id'], '3.00'
    )
    portion_output = create_stock_item(
        'PORTION-OUT', 'Portion Output', 'kg', '0', category_id, owner['id'],
        '0.00', item_type='portioned_item',
    )
    portioning = create_bulk_portioning(
        portion_source, portion_output, '0.5', owner['id']
    )

    conn = db.get_db_connection()
    try:
        assert conn.execute(
            'SELECT company_id FROM manufacturing_transactions WHERE id = ?',
            (transaction['transaction_id'],),
        ).fetchone()['company_id'] == owner['company_id']
        assert conn.execute(
            'SELECT company_id FROM portioning_transactions WHERE session_id = ?',
            (portioning['session_id'],),
        ).fetchone()['company_id'] == owner['company_id']
        assert len(list_manufacturing_history()) == 1
        assert len(list_recent_portioning()) == 1
        assert conn.execute(
            'SELECT quantity FROM stock_items WHERE id = ?',
            (ingredient_id,),
        ).fetchone()['quantity'] == '8'
        assert conn.execute(
            'SELECT quantity FROM stock_items WHERE id = ?',
            (portion_output,),
        ).fetchone()['quantity'] == '0.5'
    finally:
        conn.close()
        clear_tenant_context()


def test_resend_replaces_previous_verification_token(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'resend-test.db')
    db.init_db()
    user = register_company(
        'Resend Kitchen', 'resend@example.test',
        'resend-password-1234', 'resend-password-1234',
    )
    old_token = user['verification_token']
    new_token = None
    from services import create_email_verification_token
    new_token = create_email_verification_token(user['id'])
    assert new_token and new_token != old_token
    assert verify_email_token(old_token)[0] == 'invalid'
    assert verify_email_token(new_token) == ('verified', user['id'])


def test_email_settings_encrypt_smtp_password(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'email-settings-test.db')
    db.init_db()
    user = register_company(
        'Mail Kitchen', 'mail@example.test',
        'mail-settings-password-123', 'mail-settings-password-123',
    )
    update_email_settings({
        'smtp_server': 'smtp.example.test',
        'smtp_port': '587',
        'smtp_username': 'smtp-user',
        'smtp_password': 'secret-smtp-password',
        'sender_email': 'noreply@example.test',
        'sender_display_name': 'Kitchen Factory Lite',
    }, company_id=user['company_id'])
    settings = get_email_settings(user['company_id'])
    assert settings['smtp_password'] == 'secret-smtp-password'
    assert settings['smtp_password_configured']
    conn = db.get_db_connection()
    try:
        stored = conn.execute(
            """SELECT value FROM company_settings
               WHERE company_id = ? AND key = 'email_smtp_password'""",
            (user['company_id'],),
        ).fetchone()['value']
        assert stored != 'secret-smtp-password'
    finally:
        conn.close()
