"""Permanent seed inventory for the shared demo company."""

from datetime import datetime
from decimal import Decimal

from db import get_db_connection

DEMO_STOCK_ITEMS = [
    {'code': 'BAK001', 'name': 'Cake Flour', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '25', 'cost_per_unit': '18.50', 'category': 'Baking Ingredients', 'status': 'Active'},
    {'code': 'BAK002', 'name': 'Bread Flour', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '25', 'cost_per_unit': '17.00', 'category': 'Baking Ingredients', 'status': 'Active'},
    {'code': 'BAK003', 'name': 'White Sugar', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '20', 'cost_per_unit': '22.00', 'category': 'Baking Ingredients', 'status': 'Active'},
    {'code': 'BAK004', 'name': 'Brown Sugar', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '15', 'cost_per_unit': '24.00', 'category': 'Baking Ingredients', 'status': 'Active'},
    {'code': 'BAK005', 'name': 'Baking Powder', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '5', 'cost_per_unit': '65.00', 'category': 'Baking Ingredients', 'status': 'Active'},
    {'code': 'BEV001', 'name': 'Coca-Cola Syrup', 'item_type': 'raw_material', 'unit': 'L', 'quantity': '20', 'cost_per_unit': '45.00', 'category': 'Beverages', 'status': 'Active'},
    {'code': 'BEV002', 'name': 'Orange Juice Concentrate', 'item_type': 'raw_material', 'unit': 'L', 'quantity': '15', 'cost_per_unit': '55.00', 'category': 'Beverages', 'status': 'Active'},
    {'code': 'BEV003', 'name': 'Coffee Beans', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '10', 'cost_per_unit': '180.00', 'category': 'Beverages', 'status': 'Active'},
    {'code': 'BEV004', 'name': 'Rooibos Tea', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '5', 'cost_per_unit': '95.00', 'category': 'Beverages', 'status': 'Active'},
    {'code': 'BEV005', 'name': 'Mineral Water', 'item_type': 'raw_material', 'unit': 'L', 'quantity': '100', 'cost_per_unit': '8.00', 'category': 'Beverages', 'status': 'Active'},
    {'code': 'BRE001', 'name': 'Burger Buns', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '15', 'cost_per_unit': '30.00', 'category': 'Bread', 'status': 'Active'},
    {'code': 'BRE002', 'name': 'Hot Dog Rolls', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '10', 'cost_per_unit': '28.00', 'category': 'Bread', 'status': 'Active'},
    {'code': 'BRE003', 'name': 'Sliced White Bread', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '20', 'cost_per_unit': '25.00', 'category': 'Bread', 'status': 'Active'},
    {'code': 'BRE004', 'name': 'Pita Bread', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '8', 'cost_per_unit': '35.00', 'category': 'Bread', 'status': 'Active'},
    {'code': 'BRE005', 'name': 'Wraps', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '12', 'cost_per_unit': '40.00', 'category': 'Bread', 'status': 'Active'},
    {'code': 'CHE001', 'name': 'Cheddar Cheese', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '20', 'cost_per_unit': '110.00', 'category': 'Cheese', 'status': 'Active'},
    {'code': 'CHE002', 'name': 'Mozzarella Cheese', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '20', 'cost_per_unit': '120.00', 'category': 'Cheese', 'status': 'Active'},
    {'code': 'CHE003', 'name': 'Parmesan Cheese', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '5', 'cost_per_unit': '220.00', 'category': 'Cheese', 'status': 'Active'},
    {'code': 'CHE004', 'name': 'Feta Cheese', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '8', 'cost_per_unit': '145.00', 'category': 'Cheese', 'status': 'Active'},
    {'code': 'CHE005', 'name': 'Gouda Cheese', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '10', 'cost_per_unit': '125.00', 'category': 'Cheese', 'status': 'Active'},
    {'code': 'CON001', 'name': 'Tomato Sauce', 'item_type': 'raw_material', 'unit': 'L', 'quantity': '15', 'cost_per_unit': '28.00', 'category': 'Condiments', 'status': 'Active'},
    {'code': 'CON002', 'name': 'Mustard', 'item_type': 'raw_material', 'unit': 'L', 'quantity': '8', 'cost_per_unit': '35.00', 'category': 'Condiments', 'status': 'Active'},
    {'code': 'CON003', 'name': 'Mayonnaise', 'item_type': 'raw_material', 'unit': 'L', 'quantity': '10', 'cost_per_unit': '42.00', 'category': 'Condiments', 'status': 'Active'},
    {'code': 'CON004', 'name': 'Sweet Chilli Sauce', 'item_type': 'manufactured_item', 'unit': 'L', 'quantity': '8', 'cost_per_unit': '48.00', 'category': 'Condiments', 'status': 'Active'},
    {'code': 'CON005', 'name': 'BBQ Sauce', 'item_type': 'manufactured_item', 'unit': 'L', 'quantity': '10', 'cost_per_unit': '45.00', 'category': 'Condiments', 'status': 'Active'},
    {'code': 'CNF001', 'name': 'Chocolate Chips', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '8', 'cost_per_unit': '95.00', 'category': 'Confectionery', 'status': 'Active'},
    {'code': 'CNF002', 'name': 'Marshmallows', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '5', 'cost_per_unit': '65.00', 'category': 'Confectionery', 'status': 'Active'},
    {'code': 'CNF003', 'name': 'Sprinkles', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '3', 'cost_per_unit': '120.00', 'category': 'Confectionery', 'status': 'Active'},
    {'code': 'DAI001', 'name': 'Full Cream Milk', 'item_type': 'raw_material', 'unit': 'L', 'quantity': '50', 'cost_per_unit': '18.00', 'category': 'Dairy', 'status': 'Active'},
    {'code': 'DAI002', 'name': 'Fresh Cream', 'item_type': 'raw_material', 'unit': 'L', 'quantity': '15', 'cost_per_unit': '42.00', 'category': 'Dairy', 'status': 'Active'},
    {'code': 'DAI003', 'name': 'Butter', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '10', 'cost_per_unit': '115.00', 'category': 'Dairy', 'status': 'Active'},
    {'code': 'DAI004', 'name': 'Yoghurt Plain', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '10', 'cost_per_unit': '55.00', 'category': 'Dairy', 'status': 'Active'},
    {'code': 'DRY001', 'name': 'Rice', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '50', 'cost_per_unit': '22.00', 'category': 'Dry Goods', 'status': 'Active'},
    {'code': 'DRY002', 'name': 'Pasta Shells', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '30', 'cost_per_unit': '25.00', 'category': 'Dry Goods', 'status': 'Active'},
    {'code': 'DRY003', 'name': 'Lentils', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '15', 'cost_per_unit': '28.00', 'category': 'Dry Goods', 'status': 'Active'},
    {'code': 'DRY004', 'name': 'Couscous', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '10', 'cost_per_unit': '35.00', 'category': 'Dry Goods', 'status': 'Active'},
    {'code': 'FRZ001', 'name': 'Frozen Chips', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '40', 'cost_per_unit': '28.00', 'category': 'Frozen Goods', 'status': 'Active'},
    {'code': 'FRZ002', 'name': 'Frozen Peas', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '20', 'cost_per_unit': '24.00', 'category': 'Frozen Goods', 'status': 'Active'},
    {'code': 'FRZ003', 'name': 'Frozen Mixed Veg', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '20', 'cost_per_unit': '26.00', 'category': 'Frozen Goods', 'status': 'Active'},
    {'code': 'FRT001', 'name': 'Tomatoes', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '20', 'cost_per_unit': '18.00', 'category': 'Fruit', 'status': 'Active'},
    {'code': 'FRT002', 'name': 'Lemons', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '10', 'cost_per_unit': '22.00', 'category': 'Fruit', 'status': 'Active'},
    {'code': 'FRT003', 'name': 'Avocados', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '8', 'cost_per_unit': '45.00', 'category': 'Fruit', 'status': 'Active'},
    {'code': 'HER001', 'name': 'Parsley', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '2', 'cost_per_unit': '90.00', 'category': 'Herbs', 'status': 'Active'},
    {'code': 'HER002', 'name': 'Coriander', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '2', 'cost_per_unit': '95.00', 'category': 'Herbs', 'status': 'Active'},
    {'code': 'HER003', 'name': 'Rosemary', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '1', 'cost_per_unit': '120.00', 'category': 'Herbs', 'status': 'Active'},
    {'code': 'MEA001', 'name': 'Beef Mince', 'item_type': 'portioned_item', 'unit': 'kg', 'quantity': '30', 'cost_per_unit': '95.00', 'category': 'Meat', 'status': 'Active'},
    {'code': 'MEA002', 'name': 'Beef Patties', 'item_type': 'portioned_item', 'unit': 'kg', 'quantity': '25', 'cost_per_unit': '110.00', 'category': 'Meat', 'status': 'Active'},
    {'code': 'MEA003', 'name': 'Rump Steak', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '20', 'cost_per_unit': '180.00', 'category': 'Meat', 'status': 'Active'},
    {'code': 'OIL001', 'name': 'Sunflower Oil', 'item_type': 'raw_material', 'unit': 'L', 'quantity': '30', 'cost_per_unit': '35.00', 'category': 'Oils', 'status': 'Active'},
    {'code': 'OIL002', 'name': 'Olive Oil', 'item_type': 'raw_material', 'unit': 'L', 'quantity': '10', 'cost_per_unit': '120.00', 'category': 'Oils', 'status': 'Active'},
    {'code': 'PAS001', 'name': 'Spaghetti', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '25', 'cost_per_unit': '24.00', 'category': 'Pasta', 'status': 'Active'},
    {'code': 'PAS002', 'name': 'Penne Pasta', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '25', 'cost_per_unit': '24.00', 'category': 'Pasta', 'status': 'Active'},
    {'code': 'POL001', 'name': 'Chicken Breast', 'item_type': 'portioned_item', 'unit': 'kg', 'quantity': '30', 'cost_per_unit': '85.00', 'category': 'Poultry', 'status': 'Active'},
    {'code': 'POL002', 'name': 'Chicken Wings', 'item_type': 'portioned_item', 'unit': 'kg', 'quantity': '25', 'cost_per_unit': '65.00', 'category': 'Poultry', 'status': 'Active'},
    {'code': 'POL003', 'name': 'Chicken Whole', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '87', 'cost_per_unit': '43.50', 'category': 'Poultry', 'status': 'Active'},
    {'code': 'PRE001', 'name': 'Cheese Sauce', 'item_type': 'raw_material', 'unit': 'L', 'quantity': '10', 'cost_per_unit': '55.00', 'category': 'Prepared Foods', 'status': 'Active'},
    {'code': 'PRE002', 'name': 'Pepper Sauce', 'item_type': 'raw_material', 'unit': 'L', 'quantity': '10', 'cost_per_unit': '52.00', 'category': 'Prepared Foods', 'status': 'Active'},
    {'code': 'RIC001', 'name': 'Basmati Rice', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '30', 'cost_per_unit': '32.00', 'category': 'Rice & Grains', 'status': 'Active'},
    {'code': 'RIC002', 'name': 'Brown Rice', 'item_type': 'raw_material', 'unit': 'kg', 'quantity': '20', 'cost_per_unit': '30.00', 'category': 'Rice & Grains', 'status': 'Active'},
    {'code': 'SAU001', 'name': 'Tomato Base Sauce', 'item_type': 'raw_material', 'unit': 'L', 'quantity': '15', 'cost_per_unit': '28.00', 'category': 'Sauces', 'status': 'Active'},
    {'code': 'SAU002', 'name': 'Alfredo Sauce', 'item_type': 'manufactured_item', 'unit': 'L', 'quantity': '10', 'cost_per_unit': '45.00', 'category': 'Sauces', 'status': 'Active'},
    {'code': 'SAU003', 'name': 'Mushroom Sauce', 'item_type': 'manufactured_item', 'unit': 'L', 'quantity': '10', 'cost_per_unit': '48.00', 'category': 'Sauces', 'status': 'Active'},
]


def seed_demo_stock_items(company_id, user_id):
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        stock_count = conn.execute(
            'SELECT COUNT(*) FROM stock_items WHERE company_id = ?',
            (company_id,),
        ).fetchone()[0]
        if stock_count:
            conn.rollback()
            return 0

        category_rows = conn.execute(
            'SELECT id, name FROM categories WHERE company_id = ? AND active = 1',
            (company_id,),
        ).fetchall()
        category_ids = {row['name']: row['id'] for row in category_rows}
        missing_categories = sorted({
            item['category'] for item in DEMO_STOCK_ITEMS
            if item['category'] not in category_ids
        })
        if missing_categories:
            raise ValueError(
                'Demo stock categories are missing: '
                + ', '.join(missing_categories)
            )

        now = datetime.utcnow().isoformat(timespec='seconds')
        imported_count = 0
        for item in DEMO_STOCK_ITEMS:
            cursor = conn.execute(
                '''INSERT INTO stock_items
                   (company_id, code, name, item_type, unit, quantity, category_id,
                    active, date_created, date_modified, created_by, modified_by, unit_cost)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    company_id,
                    item['code'],
                    item['name'],
                    item['item_type'],
                    item['unit'],
                    str(Decimal(item['quantity'])),
                    category_ids[item['category']],
                    int(item['status'] == 'Active'),
                    now,
                    now,
                    user_id,
                    user_id,
                    str(Decimal(item['cost_per_unit'])),
                ),
            )
            imported_count += cursor.rowcount
        conn.commit()
        return imported_count
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
