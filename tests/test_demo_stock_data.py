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
    assert all(
        isinstance(item['quantity'], (int, float))
        and isinstance(item['cost_per_unit'], float)
        for item in DEMO_STOCK_ITEMS
    )
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
        assert isinstance(cake_flour['quantity'], float)
        assert isinstance(cake_flour['unit_cost'], float)
        assert cake_flour['quantity'] == 25.0
        assert cake_flour['unit_cost'] == 18.50
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


def test_legacy_string_stock_values_are_migrated_to_real(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'demo-stock-legacy-test.db')
    db.init_db()
    demo_user = register_company(
        'Legacy Demo Stock Test',
        'legacy-demo-stock@example.test',
        'legacy-demo-stock-password-123',
        'legacy-demo-stock-password-123',
    )
    assert seed_demo_stock_items(demo_user['company_id'], demo_user['id']) == 62

    conn = db.get_db_connection()
    try:
        conn.execute('PRAGMA foreign_keys = OFF')
        conn.execute('PRAGMA legacy_alter_table = ON')
        conn.execute('ALTER TABLE stock_items RENAME TO stock_items_numeric')
        conn.execute(
            '''CREATE TABLE stock_items (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   company_id INTEGER,
                   code TEXT NOT NULL,
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
            '''INSERT INTO stock_items
               SELECT id, company_id, code, name, item_type, unit,
                      CAST(quantity AS TEXT), category_id, active, date_created,
                      date_modified, created_by, modified_by,
                      CAST(unit_cost AS TEXT), notes
               FROM stock_items_numeric'''
        )
        conn.execute('DROP TABLE stock_items_numeric')
        conn.execute(
            '''CREATE UNIQUE INDEX idx_stock_items_company_code
               ON stock_items(company_id, code COLLATE NOCASE)'''
        )
        conn.commit()
    finally:
        conn.close()

    db.init_db()
    set_tenant_context(demo_user['company_id'], demo_user['id'])
    try:
        cake_flour = next(
            item for item in list_stock_items() if item['code'] == 'BAK001'
        )
        assert cake_flour['quantity'] == 25.0
        assert cake_flour['unit_cost'] == 18.5
        conn = db.get_db_connection()
        try:
            stock_types = {
                row['name']: row['type'].upper()
                for row in conn.execute('PRAGMA table_info(stock_items)')
            }
            stored_types = conn.execute(
                '''SELECT typeof(quantity) AS quantity_type,
                          typeof(unit_cost) AS unit_cost_type
                   FROM stock_items WHERE company_id = ? AND code = 'BAK001' ''',
                (demo_user['company_id'],),
            ).fetchone()
        finally:
            conn.close()
        assert stock_types['quantity'] == 'REAL'
        assert stock_types['unit_cost'] == 'REAL'
        assert stored_types['quantity_type'] == 'real'
        assert stored_types['unit_cost_type'] == 'real'
    finally:
        clear_tenant_context()
