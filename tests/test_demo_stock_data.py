from decimal import Decimal

import db
from db import clear_tenant_context, set_tenant_context
from demo_stock_data import DEMO_STOCK_ITEMS, seed_demo_stock_items
from services import list_stock_items, register_company


def test_demo_stock_items_seed_once_and_keep_total_cost_dynamic(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'demo-stock-test.db')
    db.init_db()
    demo_user = register_company(
        'Demo Stock Test',
        'demo-stock@example.test',
        'demo-stock-password-123',
        'demo-stock-password-123',
    )

    imported_count = seed_demo_stock_items(
        demo_user['company_id'],
        demo_user['id'],
    )
    assert imported_count == len(DEMO_STOCK_ITEMS) == 62
    assert seed_demo_stock_items(
        demo_user['company_id'],
        demo_user['id'],
    ) == 0

    conn = db.get_db_connection()
    try:
        count = conn.execute(
            'SELECT COUNT(*) FROM stock_items WHERE company_id = ?',
            (demo_user['company_id'],),
        ).fetchone()[0]
        columns = {
            row['name'] for row in conn.execute('PRAGMA table_info(stock_items)')
        }
    finally:
        conn.close()

    assert count == 62
    assert 'total_cost' not in columns

    set_tenant_context(demo_user['company_id'], demo_user['id'])
    try:
        items = list_stock_items()
        cake_flour = next(item for item in items if item['code'] == 'BAK001')
        assert cake_flour['quantity'] == '25'
        assert cake_flour['unit_cost'] == '18.50'
        assert cake_flour['total_cost'] == Decimal('462.50')
    finally:
        clear_tenant_context()


def test_demo_stock_seeding_does_not_add_items_to_nonempty_inventory(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'demo-stock-existing-test.db')
    db.init_db()
    demo_user = register_company(
        'Existing Stock Test',
        'existing-stock@example.test',
        'existing-stock-password-123',
        'existing-stock-password-123',
    )

    conn = db.get_db_connection()
    try:
        category_id = conn.execute(
            'SELECT id FROM categories WHERE company_id = ? LIMIT 1',
            (demo_user['company_id'],),
        ).fetchone()['id']
        conn.execute(
            '''INSERT INTO stock_items
               (company_id, code, name, item_type, unit, quantity, category_id,
                date_created, date_modified, created_by, modified_by, unit_cost)
               VALUES (?, 'EXIST001', 'Existing Item', 'raw_material', 'kg',
                       '1', ?, 'now', 'now', ?, ?, '1.00')''',
            (
                demo_user['company_id'],
                category_id,
                demo_user['id'],
                demo_user['id'],
            ),
        )
        conn.commit()
    finally:
        conn.close()

    assert seed_demo_stock_items(
        demo_user['company_id'],
        demo_user['id'],
    ) == 0

    conn = db.get_db_connection()
    try:
        count = conn.execute(
            'SELECT COUNT(*) FROM stock_items WHERE company_id = ?',
            (demo_user['company_id'],),
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1
