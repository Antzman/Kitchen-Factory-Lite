"""Permanent menu and recipe seed data for the shared demo company."""

from db import get_db_connection
from services import (
    create_category,
    create_menu_category,
    create_menu_item,
    create_stock_item,
    get_menu_item_recipe,
    list_menu_categories,
    list_menu_items,
    list_stock_items,
    save_menu_recipe_line,
    set_category_active,
    set_menu_category_active,
)

_DEMO_MENU_CATEGORIES = (
    'Burgers',
    'Pizza',
    'Wraps',
    'Steaks',
    'Beverages',
    'Desserts',
)

_DEMO_MENU_ITEMS = (
    ('MNU001', 'Beef Burger', 'Burgers', '89.00'),
    ('MNU002', 'Cheese Burger', 'Burgers', '95.00'),
    ('MNU003', 'Chicken Burger', 'Burgers', '85.00'),
    ('MNU004', 'Chicken Wrap', 'Wraps', '79.00'),
    ('MNU005', 'Margherita Pizza', 'Pizza', '109.00'),
    ('MNU006', 'Chicken Pizza', 'Pizza', '129.00'),
    ('MNU007', 'Rump Steak 300g', 'Steaks', '199.00'),
    ('MNU008', 'Coca-Cola', 'Beverages', '25.00'),
    ('MNU009', 'Coffee', 'Beverages', '30.00'),
    ('MNU010', 'Chocolate Brownie', 'Desserts', '55.00'),
)

_DEMO_RECIPES = {
    'MNU001': (('BRE001', '0.120'), ('MEA002', '0.180'),
               ('CHE001', '0.020'), ('CON005', '0.030')),
    'MNU002': (('BRE001', '0.120'), ('MEA002', '0.180'),
               ('CHE001', '0.040'), ('CON005', '0.030')),
    'MNU003': (('BRE001', '0.120'), ('POL001', '0.180'),
               ('CHE001', '0.020'), ('CON003', '0.030')),
    'MNU004': (('BRE005', '0.100'), ('POL001', '0.180'),
               ('CON003', '0.020'), ('FRT001', '0.030')),
    'MNU005': (('BRE006', '0.250'), ('SAU001', '0.080'),
               ('CHE002', '0.120')),
    'MNU006': (('BRE006', '0.250'), ('SAU001', '0.080'),
               ('CHE002', '0.120'), ('POL001', '0.120')),
    'MNU007': (('MEA003', '0.300'), ('PRE002', '0.080'),
               ('FRZ001', '0.250')),
    'MNU008': (('BEV001', '0.050'),),
    'MNU009': (('BEV003', '0.015'), ('DAI001', '0.100')),
    'MNU010': (('BAK001', '0.080'), ('CNF001', '0.050'),
               ('DAI003', '0.030'), ('BAK003', '0.040')),
}

_RECIPE_ITEM_TYPE_BY_STOCK_TYPE = {
    'raw_material': 'Stock Item',
    'manufactured_item': 'Manufactured Item',
    'portioned_item': 'Portioned Item',
}


def _ensure_bread_category(company_id):
    conn = get_db_connection()
    try:
        category = conn.execute(
            '''SELECT id, active FROM categories
               WHERE company_id = ? AND name = ? COLLATE NOCASE''',
            (company_id, 'Bread'),
        ).fetchone()
    finally:
        conn.close()

    if category is None:
        return create_category('Bread')
    if not category['active']:
        set_category_active(category['id'], True)
    return category['id']


def seed_demo_menu_data(company_id, user_id):
    category_count = 0
    menu_item_count = 0
    recipe_line_count = 0
    stock_item_count = 0

    menu_categories = {
        row['name'].casefold(): row
        for row in list_menu_categories()
    }
    for name in _DEMO_MENU_CATEGORIES:
        category = menu_categories.get(name.casefold())
        if category is None:
            create_menu_category(name, user_id)
            category_count += 1
        elif not category['active']:
            set_menu_category_active(category['id'], True, user_id)

    stock_items = list_stock_items()
    stock_by_code = {item['code'].casefold(): item for item in stock_items}
    if 'BRE006'.casefold() not in stock_by_code:
        bread_category_id = _ensure_bread_category(company_id)
        pizza_base_id = create_stock_item(
            'BRE006', 'Pizza Base', 'kg', 20, bread_category_id, user_id,
            unit_cost='32.00', item_type='raw_material',
        )
        stock_item_count += 1
        stock_items = list_stock_items()
        if not any(item['id'] == pizza_base_id for item in stock_items):
            raise RuntimeError('Pizza Base was not persisted after creation.')
        stock_by_code = {item['code'].casefold(): item for item in stock_items}

    missing_stock_codes = sorted({
        stock_code
        for recipe in _DEMO_RECIPES.values()
        for stock_code, _ in recipe
        if stock_code.casefold() not in stock_by_code
    })
    if missing_stock_codes:
        raise ValueError(
            'Demo menu recipe inventory items are missing: '
            + ', '.join(missing_stock_codes)
        )

    category_ids = {
        row['name'].casefold(): row['id']
        for row in list_menu_categories()
    }
    menu_items = {
        item['code'].casefold(): item
        for item in list_menu_items()
    }
    for code, name, category_name, selling_price in _DEMO_MENU_ITEMS:
        if code.casefold() in menu_items:
            continue
        menu_item_id = create_menu_item(
            code,
            name,
            'Ordinary Type',
            category_ids[category_name.casefold()],
            selling_price,
            user_id,
        )
        menu_items[code.casefold()] = {'id': menu_item_id}
        menu_item_count += 1

    for menu_code, recipe in _DEMO_RECIPES.items():
        menu_item = menu_items[menu_code.casefold()]
        existing_stock_ids = {
            line['stock_item_id'] for line in get_menu_item_recipe(menu_item['id'])
        }
        for stock_code, quantity in recipe:
            stock_item = stock_by_code[stock_code.casefold()]
            if stock_item['id'] in existing_stock_ids:
                continue
            if not stock_item['active']:
                raise ValueError(
                    f'Demo menu recipe inventory item {stock_code} is inactive.'
                )
            item_type = _RECIPE_ITEM_TYPE_BY_STOCK_TYPE.get(
                stock_item['item_type']
            )
            if item_type is None:
                raise ValueError(
                    f'Demo menu recipe inventory item {stock_code} has an '
                    'unsupported item type.'
                )
            save_menu_recipe_line(
                menu_item['id'], item_type, stock_item['id'], quantity, user_id
            )
            existing_stock_ids.add(stock_item['id'])
            recipe_line_count += 1

    return {
        'categories': category_count,
        'menu_items': menu_item_count,
        'recipe_lines': recipe_line_count,
        'stock_items': stock_item_count,
    }
