import db
from db import clear_tenant_context, set_tenant_context
from services import create_stock_item, create_yield_loss_portioning, register_company


def test_yield_portioning_screen_report_export_and_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'yield-web-test.db')
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
            'company_name': 'Yield Web Kitchen',
            'email': 'yield-web@example.test',
            'password': 'yield-web-password-123',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    with client.session_transaction() as session:
        user_id = session['user_id']
        company_id = session['company_id']
        csrf_token = session['csrf_token']

    set_tenant_context(company_id, user_id)
    try:
        conn = db.get_db_connection()
        category_id = conn.execute(
            'SELECT id FROM categories WHERE company_id = ? LIMIT 1',
            (company_id,),
        ).fetchone()['id']
        conn.close()
        source_id = create_stock_item(
            'YIELD-WEB-RAW', 'Yield Web Source', 'kg', '10',
            category_id, user_id, '175.00',
        )
    finally:
        clear_tenant_context()

    response = client.post(
        '/portioning',
        data={
            'csrf_token': csrf_token,
            'action': 'yield_loss',
            'source_item_id': str(source_id),
            'original_quantity': '10',
            'expected_yield_quantity': '6',
            'usable_quantity': '5.5',
            'original_total_cost': '1750',
            'destination_item_id': '',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b'91.67%' in response.data
    assert b'R318.18/kg' in response.data
    assert b'+81.82%' in response.data

    report = client.get('/reports')
    assert b'Expected Yield' in report.data
    assert b'Yield Efficiency %' in report.data
    export = client.get('/reports/portioning/export.csv')
    assert export.status_code == 200
    assert b'Yield Efficiency %' in export.data
    assert b'R318.18/kg' in export.data
    assert b'+81.82%' in export.data

    set_tenant_context(company_id, user_id)
    try:
        conn = db.get_db_connection()
        audit = conn.execute(
            "SELECT description FROM audit_log WHERE action = 'PORTIONING COMPLETED'"
        ).fetchone()
        assert 'yield_efficiency_percentage=91.67' in audit['description']
        assert 'actual_cost_per_unit=R318.18/kg' in audit['description']
        assert 'cost_increase_percentage=+81.82' in audit['description']
        conn.close()
    finally:
        clear_tenant_context()


def test_portioning_yield_targets_are_stored(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'yield-portioning-test.db')
    db.init_db()
    owner = register_company(
        'Yield Test Kitchen', 'yield@example.test',
        'yield-test-password-123', 'yield-test-password-123',
    )
    set_tenant_context(owner['company_id'], owner['id'])
    try:
        conn = db.get_db_connection()
        category_id = conn.execute(
            'SELECT id FROM categories WHERE company_id = ? LIMIT 1',
            (owner['company_id'],),
        ).fetchone()['id']
        conn.close()
        source_id = create_stock_item(
            'YIELD-RAW', 'Yield Source', 'kg', '10', category_id, owner['id'], '0.00'
        )

        transaction = create_yield_loss_portioning(
            source_id, None, 10, 5.5, 1750, owner['id'],
            expected_yield_quantity=6,
        )

        conn = db.get_db_connection()
        try:
            row = conn.execute(
                'SELECT * FROM portioning_transactions WHERE session_id = ?',
                (transaction['session_id'],),
            ).fetchone()
            assert row['expected_yield_quantity'] == 6
            assert round(row['yield_efficiency_percentage'], 2) == 91.67
            assert round(row['actual_cost_per_unit'], 2) == 318.18
            assert round(row['cost_increase_percentage'], 2) == 81.82
        finally:
            conn.close()
    finally:
        clear_tenant_context()


def test_portioning_columns_migrate_existing_database(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'yield-migration-test.db')
    db.init_db()
    conn = db.get_db_connection()
    try:
        for column in (
            'expected_yield_quantity', 'yield_efficiency_percentage',
            'actual_cost_per_unit', 'cost_increase_percentage',
        ):
            conn.execute(f'ALTER TABLE portioning_transactions DROP COLUMN {column}')
        conn.commit()
    finally:
        conn.close()

    db.init_db()

    conn = db.get_db_connection()
    try:
        columns = {
            row['name']: row
            for row in conn.execute('PRAGMA table_info(portioning_transactions)')
        }
        assert {
            'expected_yield_quantity', 'yield_efficiency_percentage',
            'actual_cost_per_unit', 'cost_increase_percentage',
        } <= columns.keys()
        assert all(columns[name]['dflt_value'] == '0' for name in (
            'expected_yield_quantity', 'yield_efficiency_percentage',
            'actual_cost_per_unit', 'cost_increase_percentage',
        ))
    finally:
        conn.close()
