import json
from io import BytesIO
from decimal import Decimal

import pytest

import db
from db import clear_tenant_context, seed_data, set_tenant_context
from services import (
    create_menu_category,
    create_menu_item,
    create_stock_item,
    delete_menu_category,
    get_menu_item,
    get_menu_item_recipe,
    list_menu_categories,
    menu_item_audit_entries,
    import_menu_items,
    list_menu_items,
    parse_menu_item_csv,
    process_menu_item_refund,
    process_menu_item_sale,
    register_company,
    list_stock_items,
    save_menu_recipe_line,
    validate_menu_item_import_rows,
    verify_email_token,
)


@pytest.fixture
def menu_database(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'menu-test.db')
    db.init_db()
    seed_data()
    user = register_company(
        'Menu Test Company', 'owner@example.test',
        'long-test-password-123', 'long-test-password-123',
    )
    verify_email_token(user['verification_token'])
    set_tenant_context(user['company_id'], user['id'])
    conn = db.get_db_connection()
    user_id = user['id']
    stock_category_id = conn.execute(
        "SELECT id FROM categories WHERE name = 'Prepared Foods'"
    ).fetchone()['id']
    food_category_id = conn.execute(
        "SELECT id FROM menu_categories WHERE name = 'Food'"
    ).fetchone()['id']
    conn.close()
    yield user_id, stock_category_id, food_category_id
    clear_tenant_context()


def test_menu_item_recipe_cost_and_audit(menu_database):
    user_id, stock_category_id, menu_category_id = menu_database
    stock_id = create_stock_item(
        'BUN001', 'Burger Bun', 'each', '20', stock_category_id, user_id, '4.00'
    )
    menu_id = create_menu_item(
        'BURGER001', 'Cheese Burger', 'Ordinary Menu Item', menu_category_id, '55', user_id
    )
    save_menu_recipe_line(menu_id, 'Stock Item', stock_id, '1.5', user_id)

    item = get_menu_item(menu_id)
    assert item['cost_price'] == Decimal('6.00')
    assert item['gross_profit'] == Decimal('49.00')
    assert item['gross_profit_percentage'] == Decimal('89.09090909090909090909090909')
    assert get_menu_item_recipe(menu_id)[0]['total_cost'] == Decimal('6.00')

    conn = db.get_db_connection()
    conn.execute('UPDATE stock_items SET unit_cost = ? WHERE id = ?', ('5.00', stock_id))
    conn.commit()
    conn.close()
    assert get_menu_item(menu_id)['cost_price'] == Decimal('7.50')
    assert get_menu_item_recipe(menu_id)[0]['total_cost'] == Decimal('7.50')

    entries = menu_item_audit_entries(menu_id)
    assert [entry['action'] for entry in entries] == [
        'RECIPE LINE CREATED', 'MENU ITEM CREATED'
    ]
    assert json.loads(entries[0]['new_value'])['quantity'] == '1.5'


def test_sale_refund_uses_original_recipe_snapshot(menu_database):
    user_id, stock_category_id, menu_category_id = menu_database
    stock_id = create_stock_item(
        'PATTY001', 'Beef Patty', 'kg', '10', stock_category_id, user_id, '20.00'
    )
    menu_id = create_menu_item(
        'BURGER001', 'Cheese Burger', 'Ordinary Menu Item', menu_category_id, '55', user_id
    )
    save_menu_recipe_line(menu_id, 'Stock Item', stock_id, '0.125', user_id)
    conn = db.get_db_connection()
    conn.execute('UPDATE stock_items SET unit_cost = ? WHERE id = ?', ('21.00', stock_id))
    conn.commit()
    conn.close()
    sale_id = process_menu_item_sale(menu_id, '2', user_id, 'POS-100')

    conn = db.get_db_connection()
    quantity_after_sale = Decimal(conn.execute(
        'SELECT quantity FROM stock_items WHERE id = ?', (stock_id,)
    ).fetchone()['quantity'])
    sale_unit_cost = conn.execute(
        'SELECT unit_cost FROM menu_item_inventory_lines WHERE transaction_id = ?',
        (sale_id,),
    ).fetchone()['unit_cost']
    conn.close()
    assert quantity_after_sale == Decimal('9.75')
    assert sale_unit_cost == '21.00'

    save_menu_recipe_line(menu_id, 'Stock Item', stock_id, '0.250', user_id, line_id=1)
    process_menu_item_refund(sale_id, '1', user_id, 'POS-REFUND-100')

    conn = db.get_db_connection()
    quantity_after_refund = Decimal(conn.execute(
        'SELECT quantity FROM stock_items WHERE id = ?', (stock_id,)
    ).fetchone()['quantity'])
    movements = conn.execute(
        'SELECT movement_type, quantity FROM stock_movements ORDER BY id'
    ).fetchall()
    transaction_audit = conn.execute(
        "SELECT action FROM audit_log WHERE module = 'Menu Items' AND action IN "
        "('MENU ITEM SOLD', 'MENU ITEM REFUNDED') ORDER BY id"
    ).fetchall()
    conn.close()
    assert quantity_after_refund == Decimal('9.875')
    assert [(row['movement_type'], Decimal(row['quantity'])) for row in movements] == [
        ('menu_sale', Decimal('-0.25')),
        ('menu_refund', Decimal('0.125')),
    ]
    assert [row['action'] for row in transaction_audit] == [
        'MENU ITEM SOLD', 'MENU ITEM REFUNDED'
    ]


def test_sale_with_insufficient_stock_is_atomic(menu_database):
    user_id, stock_category_id, menu_category_id = menu_database
    stock_id = create_stock_item(
        'PATTY001', 'Beef Patty', 'kg', '0.100', stock_category_id, user_id, '20.00'
    )
    menu_id = create_menu_item(
        'BURGER001', 'Cheese Burger', 'Ordinary Menu Item', menu_category_id, '55', user_id
    )
    save_menu_recipe_line(menu_id, 'Stock Item', stock_id, '0.060', user_id)
    save_menu_recipe_line(menu_id, 'Stock Item', stock_id, '0.060', user_id)

    with pytest.raises(ValueError, match='Insufficient stock'):
        process_menu_item_sale(menu_id, '1', user_id)

    conn = db.get_db_connection()
    assert conn.execute('SELECT COUNT(*) FROM stock_movements').fetchone()[0] == 0
    assert conn.execute(
        'SELECT COUNT(*) FROM menu_item_inventory_transactions'
    ).fetchone()[0] == 0
    conn.close()


def test_menu_categories_are_independent_and_protected(menu_database):
    user_id, _, menu_category_id = menu_database
    assert {row['name'] for row in list_menu_categories()} >= {'Food', 'Beverages'}
    category_id = create_menu_category('Desserts', user_id)
    menu_id = create_menu_item(
        'CAKE001', 'Chocolate Cake', 'Ordinary Menu Item', category_id, '40', user_id
    )
    with pytest.raises(ValueError, match='assigned to menu items'):
        delete_menu_category(category_id)
    assert get_menu_item(menu_id)['category_id'] == category_id


def test_menu_item_csv_import_and_validation(menu_database):
    user_id, _, _ = menu_database
    rows = parse_menu_item_csv(
        'Code,Name,Type,Category,Selling Price,Active\n'
        'DRINK001,Cola,Ordinary Type,Beverages,18.50,Yes\n'
        'STEAK001,Grilled Steak,Prep Screen Item,Food,125.00,No\n'
    )
    valid_rows, errors = validate_menu_item_import_rows(rows)
    assert errors == []
    assert [row['type_label'] for row in valid_rows] == [
        'Ordinary Type', 'Prep Screen Item'
    ]
    imported_ids = import_menu_items(rows, user_id)
    assert len(imported_ids) == 2
    assert get_menu_item(imported_ids[0])['item_type'] == 'Ordinary Type'
    assert get_menu_item(imported_ids[1])['active'] == 0

    duplicate_rows = parse_menu_item_csv(
        'Code,Name,Type,Category,Selling Price\n'
        'DRINK001,Duplicate,Ordinary Type,Beverages,20\n'
        'DRINK002,Duplicate,Ordinary Type,Missing,20\n'
    )
    valid_rows, errors = validate_menu_item_import_rows(duplicate_rows)
    assert len(valid_rows) == 0
    assert len(errors) == 2
    with pytest.raises(ValueError, match='duplicate menu item code'):
        import_menu_items(duplicate_rows, user_id)
    assert len(list_menu_items()) == 2


def test_menu_item_screens_render(menu_database, monkeypatch):
    user_id, stock_category_id, menu_category_id = menu_database
    company_id = db.current_company_id()
    stock_id = create_stock_item(
        'BUN001', 'Burger Bun', 'each', '20', stock_category_id, user_id, '4.00'
    )
    menu_id = create_menu_item(
        'BURGER001', 'Cheese Burger', 'Prep Screen Item', menu_category_id, '55', user_id
    )
    save_menu_recipe_line(menu_id, 'Stock Item', stock_id, '1', user_id)

    import app as app_module

    monkeypatch.setattr(app_module, 'DEMO_MODE', False)
    application = app_module.create_app()
    application.testing = True
    client = application.test_client()
    with client.session_transaction() as user_session:
        user_session['user_id'] = user_id
        user_session['company_id'] = company_id
        user_session['username'] = 'owner@example.test'
        user_session['csrf_token'] = 'test-csrf-token'

    assert client.get('/menu-items').status_code == 200
    assert client.get('/menuitems').status_code == 200
    assert client.get(f'/menu-items/{menu_id}').status_code == 200
    assert client.get(f'/menu-items/{menu_id}?tab=recipe').status_code == 200
    assert client.get(f'/menu-items/{menu_id}?tab=audit&mode=view').status_code == 200
    assert client.get('/settings/menu-categories').status_code == 200
    assert client.get('/menu-items/export.csv').mimetype == 'text/csv'
    assert client.get('/menu-items/import-template.csv').mimetype == 'text/csv'
    assert client.get('/menu-items/import').status_code == 200
    assert client.post(
        f'/menu-items/{menu_id}',
        data={
            'csrf_token': 'test-csrf-token',
            'code': 'BURGER001', 'name': 'Updated Burger',
            'item_type': 'Prep Screen Item', 'category_id': str(menu_category_id),
            'selling_price': '60.00', 'active': '1',
        },
        follow_redirects=True,
    ).status_code == 200
    assert client.post(
        f'/menu-items/{menu_id}/recipe',
        data={'csrf_token': 'test-csrf-token', 'item_type': 'Stock Item',
              'stock_item_id': str(stock_id), 'quantity': '0.5'},
        follow_redirects=True,
    ).status_code == 200
    assert client.post(
        '/settings/menu-categories', data={'csrf_token': 'test-csrf-token', 'name': 'Hot Drinks'},
        follow_redirects=True,
    ).status_code == 200
    set_tenant_context(company_id, user_id)
    assert get_menu_item(menu_id)['name'] == 'Updated Burger'
    import_response = client.post(
        '/menu-items/import',
        data={'csrf_token': 'test-csrf-token', 'csv_file': (BytesIO(
            b'Code,Name,Type,Category,Selling Price,Active\n'
            b'DRINK001,Cola,Ordinary Type,Beverages,18.50,Yes\n'
        ), 'menu.csv')},
        content_type='multipart/form-data',
        follow_redirects=True,
    )
    assert import_response.status_code == 200
    assert b'Imported 1 menu items successfully.' in import_response.data
    set_tenant_context(company_id, user_id)
    assert b'Ordinary Type' in client.get('/menu-items').data
    assert b'Ordinary Type' in client.get('/menu-items/export.csv').data


def test_company_data_isolation_and_company_scoped_codes(menu_database):
    first_user, first_stock_category, first_menu_category = menu_database
    first_company = db.current_company_id()
    second = register_company(
        'Another Company', 'owner2@example.test',
        'another-test-password-123', 'another-test-password-123',
    )
    conn = db.get_db_connection()
    second_stock_category = conn.execute(
        "SELECT id FROM categories WHERE company_id = ? AND name = 'Prepared Foods'",
        (second['company_id'],),
    ).fetchone()['id']
    second_menu_category = conn.execute(
        "SELECT id FROM menu_categories WHERE company_id = ? AND name = 'Food'",
        (second['company_id'],),
    ).fetchone()['id']
    conn.close()

    set_tenant_context(second['company_id'], second['id'])
    second_stock = create_stock_item(
        'SHARED001', 'Shared Code Stock', 'each', '5',
        second_stock_category, second['id'], '1.00',
    )
    second_menu = create_menu_item(
        'SHARED001', 'Shared Code Menu', 'Ordinary Menu Item',
        second_menu_category, '10.00', second['id'],
    )

    set_tenant_context(first_company, first_user)
    first_stock = create_stock_item(
        'SHARED001', 'First Company Stock', 'each', '5',
        first_stock_category, first_user, '1.00',
    )
    first_menu = create_menu_item(
        'SHARED001', 'First Company Menu', 'Ordinary Menu Item',
        first_menu_category, '10.00', first_user,
    )
    with pytest.raises(ValueError, match='existing inventory item'):
        save_menu_recipe_line(first_menu, 'Stock Item', second_stock, '1', first_user)
    assert get_menu_item(second_menu) is None
    assert all(item['id'] != second_stock for item in list_stock_items())
    assert get_menu_item(first_menu)['name'] == 'First Company Menu'

    set_tenant_context(second['company_id'], second['id'])
    assert get_menu_item(first_menu) is None
    assert get_menu_item(second_menu)['name'] == 'Shared Code Menu'
    assert any(item['id'] == second_stock for item in list_stock_items())
