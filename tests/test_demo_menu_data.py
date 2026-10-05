from decimal import Decimal

import db
from db import clear_tenant_context, seed_data, set_tenant_context
from demo_menu_data import seed_demo_menu_data
from demo_stock_data import seed_demo_stock_items
from services import (
    get_menu_item,
    get_menu_item_recipe,
    list_menu_categories,
    list_menu_items,
    list_stock_items,
    register_company,
)

_EXPECTED_ITEMS = {
    'MNU001': ('Beef Burger', 'Burgers', '89.00'),
    'MNU002': ('Cheese Burger', 'Burgers', '95.00'),
    'MNU003': ('Chicken Burger', 'Burgers', '85.00'),
    'MNU004': ('Chicken Wrap', 'Wraps', '79.00'),
    'MNU005': ('Margherita Pizza', 'Pizza', '109.00'),
    'MNU006': ('Chicken Pizza', 'Pizza', '129.00'),
    'MNU007': ('Rump Steak 300g', 'Steaks', '199.00'),
    'MNU008': ('Coca-Cola', 'Beverages', '25.00'),
    'MNU009': ('Coffee', 'Beverages', '30.00'),
    'MNU010': ('Chocolate Brownie', 'Desserts', '55.00'),
}

_EXPECTED_RECIPES = {
    'MNU001': [('BRE001', '0.120'), ('MEA002', '0.180'),
               ('CHE001', '0.020'), ('CON005', '0.030')],
    'MNU002': [('BRE001', '0.120'), ('MEA002', '0.180'),
               ('CHE001', '0.040'), ('CON005', '0.030')],
    'MNU003': [('BRE001', '0.120'), ('POL001', '0.180'),
               ('CHE001', '0.020'), ('CON003', '0.030')],
    'MNU004': [('BRE005', '0.100'), ('POL001', '0.180'),
               ('CON003', '0.020'), ('FRT001', '0.030')],
    'MNU005': [('BRE006', '0.250'), ('SAU001', '0.080'),
               ('CHE002', '0.120')],
    'MNU006': [('BRE006', '0.250'), ('SAU001', '0.080'),
               ('CHE002', '0.120'), ('POL001', '0.120')],
    'MNU007': [('MEA003', '0.300'), ('PRE002', '0.080'),
               ('FRZ001', '0.250')],
    'MNU008': [('BEV001', '0.050')],
    'MNU009': [('BEV003', '0.015'), ('DAI001', '0.100')],
    'MNU010': [('BAK001', '0.080'), ('CNF001', '0.050'),
               ('DAI003', '0.030'), ('BAK003', '0.040')],
}


def test_demo_menu_seeding_is_idempotent_and_preserves_existing_records(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'demo-menu-test.db')
    db.init_db()
    seed_data()
    demo_user = register_company(
        'Demo Menu Test',
        'demo-menu@example.test',
        'demo-menu-password-123',
        'demo-menu-password-123',
    )
    set_tenant_context(demo_user['company_id'], demo_user['id'])
    try:
        seed_demo_stock_items(demo_user['company_id'], demo_user['id'])

        seeded = seed_demo_menu_data(
            demo_user['company_id'], demo_user['id']
        )
        assert seeded == {
            'categories': 5,
            'menu_items': 10,
            'recipe_lines': 33,
            'stock_items': 1,
        }
        assert seed_demo_menu_data(
            demo_user['company_id'], demo_user['id']
        ) == {
            'categories': 0,
            'menu_items': 0,
            'recipe_lines': 0,
            'stock_items': 0,
        }

        menu_items = {item['code']: item for item in list_menu_items()}
        assert set(menu_items) >= set(_EXPECTED_ITEMS)
        for code, (name, category, price) in _EXPECTED_ITEMS.items():
            item = menu_items[code]
            assert (
                item['name'], item['category_name'], item['item_type'],
                item['selling_price'],
            ) == (name, category, 'Ordinary Type', Decimal(price))
            assert [
                (line['item_code'], line['quantity'])
                for line in get_menu_item_recipe(item['id'])
            ] == _EXPECTED_RECIPES[code]
        assert {
            category['name'] for category in list_menu_categories()
        } >= {
            'Burgers', 'Pizza', 'Wraps', 'Steaks', 'Beverages', 'Desserts'
        }

        stock = next(
            item for item in list_stock_items() if item['code'] == 'BRE006'
        )
        assert (
            stock['name'], stock['item_type'], stock['unit'], stock['quantity'],
            stock['unit_cost'], stock['active'], stock['category_name'],
        ) == ('Pizza Base', 'raw_material', 'kg', 20.0, 32.0, 1, 'Bread')

        burger = next(
            item for item in list_menu_items() if item['code'] == 'MNU001'
        )
        assert (
            burger['name'], burger['item_type'], burger['category_name'],
            burger['selling_price'], burger['cost_price'],
            burger['gross_profit'],
        ) == (
            'Beef Burger', 'Ordinary Type', 'Burgers', Decimal('89.00'),
            Decimal('26.95'), Decimal('62.05'),
        )
        assert burger['gross_profit_percentage'] == (
            Decimal('62.05') / Decimal('89.00') * Decimal('100')
        )
        assert [
            (line['item_code'], line['quantity'])
            for line in get_menu_item_recipe(burger['id'])
        ] == [
            ('BRE001', '0.120'),
            ('MEA002', '0.180'),
            ('CHE001', '0.020'),
            ('CON005', '0.030'),
        ]

        conn = db.get_db_connection()
        try:
            conn.execute(
                'UPDATE menu_items SET selling_price = ? WHERE id = ?',
                ('100.00', burger['id']),
            )
            burger_bun_id = next(
                item['id'] for item in list_stock_items()
                if item['code'] == 'BRE001'
            )
            cheddar_id = next(
                item['id'] for item in list_stock_items()
                if item['code'] == 'CHE001'
            )
            conn.execute(
                '''UPDATE menu_item_recipe_lines SET quantity = ?
                   WHERE menu_item_id = ? AND stock_item_id = ?''',
                ('0.500', burger['id'], burger_bun_id),
            )
            conn.execute(
                '''DELETE FROM menu_item_recipe_lines
                   WHERE menu_item_id = ? AND stock_item_id = ?''',
                (burger['id'], cheddar_id),
            )
            conn.commit()
        finally:
            conn.close()

        repaired = seed_demo_menu_data(
            demo_user['company_id'], demo_user['id']
        )
        assert repaired == {
            'categories': 0,
            'menu_items': 0,
            'recipe_lines': 1,
            'stock_items': 0,
        }
        updated_burger = get_menu_item(burger['id'])
        assert updated_burger['selling_price'] == Decimal('100.00')
        recipe_by_code = {
            line['item_code']: line for line in get_menu_item_recipe(burger['id'])
        }
        assert recipe_by_code['BRE001']['quantity'] == '0.500'
        assert recipe_by_code['CHE001']['quantity'] == '0.020'
        assert len(recipe_by_code) == 4

        conn = db.get_db_connection()
        try:
            assert conn.execute(
                'SELECT COUNT(*) FROM menu_categories WHERE company_id = ?',
                (demo_user['company_id'],),
            ).fetchone()[0] == 7
            assert conn.execute(
                'SELECT COUNT(*) FROM menu_items WHERE company_id = ?',
                (demo_user['company_id'],),
            ).fetchone()[0] == 10
            assert conn.execute(
                '''SELECT COUNT(*) FROM menu_item_recipe_lines rl
                   JOIN menu_items mi ON mi.id = rl.menu_item_id
                   WHERE mi.company_id = ?''',
                (demo_user['company_id'],),
            ).fetchone()[0] == 33
            assert conn.execute(
                '''SELECT COUNT(*) FROM stock_items
                   WHERE company_id = ? AND code = 'BRE006' ''',
                (demo_user['company_id'],),
            ).fetchone()[0] == 1
        finally:
            conn.close()
    finally:
        clear_tenant_context()


def test_demo_menu_recipe_cost_uses_current_stock_unit_cost(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'demo-menu-cost-test.db')
    db.init_db()
    seed_data()
    demo_user = register_company(
        'Demo Menu Cost Test',
        'demo-menu-cost@example.test',
        'demo-menu-cost-password-123',
        'demo-menu-cost-password-123',
    )
    set_tenant_context(demo_user['company_id'], demo_user['id'])
    try:
        seed_demo_stock_items(demo_user['company_id'], demo_user['id'])
        seed_demo_menu_data(demo_user['company_id'], demo_user['id'])

        cola = next(item for item in list_menu_items() if item['code'] == 'MNU008')
        cola_syrup = next(
            item for item in list_stock_items() if item['code'] == 'BEV001'
        )
        conn = db.get_db_connection()
        try:
            conn.execute(
                'UPDATE stock_items SET unit_cost = ? WHERE id = ?',
                ('50.00', cola_syrup['id']),
            )
            conn.commit()
        finally:
            conn.close()

        refreshed_cola = get_menu_item(cola['id'])
        assert refreshed_cola['cost_price'] == Decimal('2.50')
        assert refreshed_cola['gross_profit'] == Decimal('22.50')
        assert refreshed_cola['gross_profit_percentage'] == Decimal('90')
        assert get_menu_item_recipe(cola['id'])[0]['total_cost'] == Decimal('2.50')
    finally:
        clear_tenant_context()


def test_demo_mode_startup_logs_menu_seed_counts_and_restarts_cleanly(
    tmp_path, monkeypatch, caplog,
):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'demo-menu-startup-test.db')
    caplog.set_level('INFO', logger='app')
    import app as app_module

    monkeypatch.setattr(app_module, 'DEMO_MODE', True)

    app_module.create_app()
    assert (
        'Demo menu database seeded; categories=5 menu_items=10 '
        'recipe_lines=33 stock_items=1'
    ) in caplog.text
    menu_page = app_module.app.test_client().get('/menu-items')
    assert menu_page.status_code == 200
    for name, _, _ in _EXPECTED_ITEMS.values():
        assert name.encode() in menu_page.data

    caplog.clear()
    app_module.create_app()
    assert (
        'Demo menu database seeded; categories=0 menu_items=0 '
        'recipe_lines=0 stock_items=0'
    ) in caplog.text
