import sqlite3
from decimal import Decimal

import db
from db import clear_tenant_context, set_tenant_context
from services import (
    authenticate_user,
    create_bulk_portioning,
    create_email_verification_token,
    create_manufacturing_transaction,
    create_password_reset_token,
    create_stock_item,
    get_user_by_id,
    list_manufacturing_history,
    list_recent_portioning,
    register_company,
    reset_password,
    update_user,
    verify_email_token,
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
    assert user['active'] == 1
    assert user['email_verified'] == 1
    assert user['verified_at']
    assert authenticate_user('owner@example.test', 'correct-horse-battery-123')['id'] == user['id']

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


def test_stock_item_total_cost_is_calculated_without_database_storage(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'stock-cost-test.db')
    db.init_db()
    user = register_company(
        'Cost Test Kitchen', 'cost-owner@example.test',
        'cost-test-password-123', 'cost-test-password-123',
    )
    set_tenant_context(user['company_id'], user['id'])
    try:
        conn = db.get_db_connection()
        try:
            category_id = conn.execute(
                'SELECT id FROM categories WHERE company_id = ? LIMIT 1',
                (user['company_id'],),
            ).fetchone()['id']
            stock_columns = {
                row['name'] for row in conn.execute('PRAGMA table_info(stock_items)')
            }
        finally:
            conn.close()

        from services import create_stock_item, list_stock_items, stock_item_report

        create_stock_item(
            'COST001', 'Cost Test Item', 'kg', '3', category_id,
            user['id'], unit_cost='2.25',
        )
        item = list_stock_items()[0]
        report_rows, _, _ = stock_item_report()

        assert item['unit_cost'] == '2.25'
        assert item['total_cost'] == Decimal('6.75')
        assert report_rows[0]['total_cost'] == Decimal('6.75')
        assert 'total_cost' not in stock_columns
    finally:
        clear_tenant_context()


def test_local_registration_and_admin_temporary_password_flow(
    tmp_path, monkeypatch, caplog,
):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'web-auth-test.db')
    monkeypatch.delenv('FLASK_ENV', raising=False)
    import app as app_module

    monkeypatch.setattr(app_module, 'DEMO_MODE', False)
    application = app_module.create_app()
    application.testing = True
    client = application.test_client()

    register_page = client.get('/register')
    with client.session_transaction() as session:
        csrf_token = session['csrf_token']
    assert register_page.status_code == 200
    assert (
        f'<input type="hidden" name="csrf_token" value="{csrf_token}">'.encode()
        in register_page.data
    )
    assert client.post('/register', data={'company_name': 'CSRF rejection'}).status_code == 302
    assert (
        'CSRF validation failed; action=rejected reason=submitted token missing'
    ) in caplog.text
    response = client.post(
        '/register',
        data={
            'csrf_token': csrf_token,
            'company_name': 'Local Test Kitchen',
            'email': 'local-owner@example.test',
            'password': 'local-registration-password-123',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b'Company registered successfully. You are now signed in.' in response.data
    dashboard_page = client.get('/dashboard')
    with client.session_transaction() as session:
        csrf_token = session['csrf_token']
    assert dashboard_page.status_code == 200
    assert (
        f'<input type="hidden" name="csrf_token" value="{csrf_token}">'.encode()
        in dashboard_page.data
    )

    conn = db.get_db_connection()
    registered = conn.execute(
        'SELECT email_verified, active FROM users WHERE email = ?',
        ('local-owner@example.test',),
    ).fetchone()
    conn.close()
    assert registered['email_verified'] == 1
    assert registered['active'] == 1

    with client.session_transaction() as session:
        owner_id = session['user_id']
        company_id = session['company_id']
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
        data={'csrf_token': csrf_token},
        follow_redirects=True,
    ).status_code == 200
    import re
    temporary_password = re.search(
        rb'Temporary password: ([A-Za-z0-9_-]+)', client.get('/users').data,
    )
    assert temporary_password
    temporary_password = temporary_password.group(1).decode()
    assert authenticate_user('manager@example.test', temporary_password)['id'] == manager['id']
    conn = db.get_db_connection()
    assert conn.execute(
        'SELECT must_change_password FROM users WHERE id = ?', (manager['id'],)
    ).fetchone()['must_change_password'] == 1
    conn.close()

    with client.session_transaction() as session:
        csrf_token = session['csrf_token']
    client.post('/logout', data={'csrf_token': csrf_token})
    client.get('/login')
    with client.session_transaction() as session:
        csrf_token = session['csrf_token']
    response = client.post(
        '/login',
        data={
            'csrf_token': csrf_token,
            'email': 'manager@example.test',
            'password': temporary_password,
        },
        follow_redirects=True,
    )
    assert b'Choose a New Password' in response.data
    assert client.get('/dashboard').status_code == 302
    with client.session_transaction() as session:
        csrf_token = session['csrf_token']
    response = client.post(
        '/change-password',
        data={
            'csrf_token': csrf_token,
            'password': 'manager-new-password-789',
            'confirm_password': 'manager-new-password-789',
        },
        follow_redirects=True,
    )
    assert b'Password updated. You can now continue.' in response.data
    assert client.get('/dashboard').status_code == 200
    assert authenticate_user('manager@example.test', temporary_password) is None
    assert authenticate_user('manager@example.test', 'manager-new-password-789')
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
    conn = db.get_db_connection()
    actions = {
        row['action'] for row in conn.execute(
            "SELECT action FROM audit_log WHERE company_id = ?", (company_id,)
        )
    }
    conn.close()
    assert {'PASSWORD RESET', 'TEMPORARY PASSWORD CHANGED'} <= actions


def test_development_bypasses_invalid_csrf_token_and_logs_reason(
    tmp_path, monkeypatch, caplog,
):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'development-csrf-test.db')
    monkeypatch.setenv('FLASK_ENV', 'development')
    import app as app_module

    monkeypatch.setattr(app_module, 'DEMO_MODE', False)
    application = app_module.create_app()
    application.testing = True
    client = application.test_client()
    client.get('/register')

    response = client.post(
        '/register',
        data={
            'csrf_token': 'stale-token',
            'company_name': 'Development Test Kitchen',
            'email': 'development-owner@example.test',
            'password': 'development-owner-password-123',
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b'Company registered successfully. You are now signed in.' in response.data
    assert (
        'CSRF validation failed; action=bypassed in development '
        'reason=submitted token does not match session token'
    ) in caplog.text


def test_login_csrf_token_is_rendered_from_session_and_request_state_is_logged(
    tmp_path, monkeypatch, caplog,
):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'login-csrf-test.db')
    monkeypatch.delenv('FLASK_ENV', raising=False)
    caplog.set_level('INFO', logger='app')
    import app as app_module

    monkeypatch.setattr(app_module, 'DEMO_MODE', False)
    application = app_module.create_app()
    application.testing = True
    client = application.test_client()

    login_page = client.get('/login')
    with client.session_transaction() as session:
        csrf_token = session['csrf_token']

    rendered_token = (
        f'<input type="hidden" name="csrf_token" value="{csrf_token}">'
    ).encode()
    assert rendered_token in login_page.data
    assert b'document.addEventListener' not in login_page.data
    assert 'incoming_session_cookie=False csrf_token_created=True' in caplog.text

    second_login_page = client.get('/login')
    assert rendered_token in second_login_page.data
    response = client.post(
        '/login',
        data={
            'csrf_token': csrf_token,
            'email': 'missing-user@example.test',
            'password': 'incorrect-password',
        },
    )
    assert response.status_code == 200
    assert (
        'CSRF validation succeeded; action=accepted reason=none method=POST '
        'endpoint=login incoming_session_cookie=True csrf_token_created=False'
    ) in caplog.text


def test_demo_mode_logs_in_without_credentials_or_csrf_and_shows_banner(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'demo-mode-test.db')
    import app as app_module

    monkeypatch.setattr(app_module, 'DEMO_MODE', True)
    application = app_module.create_app()
    application.testing = True
    client = application.test_client()

    dashboard = client.get('/dashboard')
    assert dashboard.status_code == 200
    assert b'DEMO MODE - Data may be reset at any time.' in dashboard.data
    with client.session_transaction() as session:
        assert session['username'] == 'demo@kitchenfactory.invalid'

    login_page = client.get('/login')
    assert b'name="email"' not in login_page.data
    assert b'name="password"' not in login_page.data
    assert b'>Sign in</button>' in login_page.data
    assert client.post('/login').status_code == 302
    assert client.post('/logout').status_code == 302
    assert client.get('/users').status_code == 200
    assert client.post('/register').status_code == 302


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


def test_production_registration_no_email_delivery_and_signs_in(
    tmp_path, monkeypatch, caplog,
):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'production-email.db')
    monkeypatch.setenv('KITCHEN_FACTORY_ENV', 'production')
    monkeypatch.delenv('RESEND_API_KEY', raising=False)

    import app as app_module

    monkeypatch.setattr(app_module, 'DEMO_MODE', False)
    application = app_module.create_app()
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
        },
        follow_redirects=True,
    )

    # Registration should sign the user in immediately and not attempt email delivery
    assert b'Company registered successfully. You are now signed in.' in response.data
    conn = db.get_db_connection()
    try:
        delivery = conn.execute(
            'SELECT COUNT(*) AS c FROM email_delivery_log'
        ).fetchone()
        assert delivery['c'] == 0
    finally:
        conn.close()
        ).fetchone()
        actions = {
            row['action'] for row in conn.execute(
                'SELECT action FROM audit_log',
            )
        }
        assert delivery['status'] == 'failed'
        assert delivery['error_type'] == 'ConnectionError'
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


def test_emergency_admin_recovery_is_scoped_and_audited(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'emergency-recovery.db')
    monkeypatch.setenv('MASTER_ADMIN_KEY', 'test-master-admin-key-never-a-password')
    import app as app_module
    from services import create_user

    monkeypatch.setattr(app_module, 'DEMO_MODE', False)
    application = app_module.create_app()
    application.testing = True
    client = application.test_client()
    client.get('/register')
    with client.session_transaction() as session:
        csrf_token = session['csrf_token']
    response = client.post(
        '/register',
        data={
            'csrf_token': csrf_token,
            'company_name': 'Emergency Recovery Kitchen',
            'email': 'recovery-admin@example.test',
            'password': 'recovery-admin-password-123',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    with client.session_transaction() as session:
        administrator_id = session['user_id']
        company_id = session['company_id']
        csrf_token = session['csrf_token']

    set_tenant_context(company_id, administrator_id)
    target_id = create_user(
        'recover-target@example.test', 'Recovery Target', 'User',
        'target-initial-password-123', 'target-initial-password-123',
    )
    conn = db.get_db_connection()
    conn.execute('UPDATE users SET account_locked = 1 WHERE id = ?', (target_id,))
    conn.commit()
    conn.close()
    assert authenticate_user('recover-target@example.test', 'target-initial-password-123') is None

    page = client.get('/admin-recovery')
    assert page.status_code == 200
    assert b'test-master-admin-key-never-a-password' not in page.data
    assert b'type="password" name="master_admin_key"' in page.data

    response = client.post(
        '/admin-recovery',
        data={
            'csrf_token': csrf_token,
            'target_user_id': str(target_id),
            'action': 'unlock_account',
            'administrator_password': 'recovery-admin-password-123',
            'master_admin_key': 'wrong-master-key',
        },
        follow_redirects=True,
    )
    assert b'Recovery credentials were not accepted.' in response.data
    conn = db.get_db_connection()
    assert conn.execute(
        'SELECT account_locked FROM users WHERE id = ?', (target_id,),
    ).fetchone()['account_locked'] == 1
    conn.close()

    recovery_form = {
        'csrf_token': csrf_token,
        'target_user_id': str(target_id),
        'administrator_password': 'recovery-admin-password-123',
        'master_admin_key': 'test-master-admin-key-never-a-password',
    }
    response = client.post(
        '/admin-recovery',
        data={
            **recovery_form,
            'target_user_id': str(administrator_id),
            'action': 'authorize_access',
        },
        follow_redirects=True,
    )
    assert b'Emergency recovery access granted' in response.data
    page = client.get('/admin-recovery')
    assert page.status_code == 200
    assert b'test-master-admin-key-never-a-password' not in page.data

    response = client.post(
        '/admin-recovery',
        data={**recovery_form, 'action': 'unlock_account'},
        follow_redirects=True,
    )
    assert b'Recovery action completed' in response.data
    conn = db.get_db_connection()
    assert conn.execute(
        'SELECT account_locked FROM users WHERE id = ?', (target_id,),
    ).fetchone()['account_locked'] == 0
    conn.close()

    response = client.post(
        '/admin-recovery',
        data={
            **recovery_form,
            'action': 'reset_password',
            'new_password': 'recovered-password-456',
            'confirm_password': 'recovered-password-456',
            'force_password_change': '1',
        },
        follow_redirects=True,
    )
    assert b'Recovery action completed' in response.data
    assert authenticate_user(
        'recover-target@example.test', 'recovered-password-456',
    )['id'] == target_id
    conn = db.get_db_connection()
    assert conn.execute(
        'SELECT must_change_password FROM users WHERE id = ?', (target_id,),
    ).fetchone()['must_change_password'] == 1
    conn.close()

    client.post(
        '/admin-recovery',
        data={**recovery_form, 'action': 'force_password_change'},
    )
    client.post(
        '/admin-recovery',
        data={**recovery_form, 'action': 'disable_account'},
    )
    assert authenticate_user('recover-target@example.test', 'recovered-password-456') is None
    client.post(
        '/admin-recovery',
        data={**recovery_form, 'action': 'enable_account'},
    )
    assert authenticate_user(
        'recover-target@example.test', 'recovered-password-456',
    )['id'] == target_id

    other_company_admin = register_company(
        'Isolated Recovery Kitchen', 'isolated-admin@example.test',
        'isolated-admin-password-123',
    )
    response = client.post(
        '/admin-recovery',
        data={
            **recovery_form,
            'target_user_id': str(other_company_admin['id']),
            'action': 'disable_account',
        },
        follow_redirects=True,
    )
    assert b'User not found in this company.' in response.data
    assert get_user_by_id(other_company_admin['id'])['active'] == 1

    conn = db.get_db_connection()
    recovery_audits = conn.execute(
        '''SELECT user_id, record_id, action, created_at, description
           FROM audit_log WHERE company_id = ? AND module = 'Authentication'
             AND (action LIKE 'EMERGENCY RECOVERY%'
                  OR action LIKE 'EMERGENCY ACCOUNT%'
                  OR action LIKE 'EMERGENCY PASSWORD%')''',
        (company_id,),
    ).fetchall()
    conn.close()
    assert recovery_audits
    assert all(row['user_id'] == administrator_id for row in recovery_audits)
    assert all(row['created_at'] for row in recovery_audits)
    assert all('Target:' in row['description'] for row in recovery_audits)
    assert {row['action'] for row in recovery_audits} >= {
        'EMERGENCY RECOVERY ACCESS DENIED',
        'EMERGENCY RECOVERY ACCESS GRANTED',
        'EMERGENCY ACCOUNT UNLOCKED',
        'EMERGENCY ACCOUNT PASSWORD RESET',
        'EMERGENCY RECOVERY FAILED',
    }

    monkeypatch.delenv('MASTER_ADMIN_KEY')
    assert client.get('/admin-recovery').status_code == 404
    assert client.post(
        '/login',
        data={
            'csrf_token': csrf_token,
            'email': 'recovery-admin@example.test',
            'password': 'test-master-admin-key-never-a-password',
        },
        follow_redirects=True,
    ).data.find(b'Logged in successfully.') == -1
    clear_tenant_context()
