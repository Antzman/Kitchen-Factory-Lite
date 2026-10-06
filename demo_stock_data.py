"""Permanent seed inventory for the shared demo company."""

from datetime import datetime
from db import get_db_connection

_DEMO_STOCK_ROWS = (
    ('BAK001', 'Cake Flour', 'raw_material', 'kg', 25, 18.50, 'Baking Ingredients'),
    ('BAK002', 'Bread Flour', 'raw_material', 'kg', 25, 17.00, 'Baking Ingredients'),
    ('BAK003', 'White Sugar', 'raw_material', 'kg', 20, 22.00, 'Baking Ingredients'),
    ('BAK004', 'Brown Sugar', 'raw_material', 'kg', 15, 24.00, 'Baking Ingredients'),
    ('BAK005', 'Baking Powder', 'raw_material', 'kg', 5, 65.00, 'Baking Ingredients'),
    ('BEV001', 'Coca-Cola Syrup', 'raw_material', 'L', 20, 45.00, 'Beverages'),
    ('BEV002', 'Orange Juice Concentrate', 'raw_material', 'L', 15, 55.00, 'Beverages'),
    ('BEV003', 'Coffee Beans', 'raw_material', 'kg', 10, 180.00, 'Beverages'),
    ('BEV004', 'Rooibos Tea', 'raw_material', 'kg', 5, 95.00, 'Beverages'),
    ('BEV005', 'Mineral Water', 'raw_material', 'L', 100, 8.00, 'Beverages'),
    ('BRE001', 'Burger Buns', 'raw_material', 'kg', 15, 30.00, 'Bread'),
    ('BRE002', 'Hot Dog Rolls', 'raw_material', 'kg', 10, 28.00, 'Bread'),
    ('BRE003', 'Sliced White Bread', 'raw_material', 'kg', 20, 25.00, 'Bread'),
    ('BRE004', 'Pita Bread', 'raw_material', 'kg', 8, 35.00, 'Bread'),
    ('BRE005', 'Wraps', 'raw_material', 'kg', 12, 40.00, 'Bread'),
    ('BRE006', 'Pizza Base', 'raw_material', 'kg', 20, 45.00, 'Bread')
    ('CHE001', 'Cheddar Cheese', 'raw_material', 'kg', 20, 110.00, 'Cheese'),
    ('CHE002', 'Mozzarella Cheese', 'raw_material', 'kg', 20, 120.00, 'Cheese'),
    ('CHE003', 'Parmesan Cheese', 'raw_material', 'kg', 5, 220.00, 'Cheese'),
    ('CHE004', 'Feta Cheese', 'raw_material', 'kg', 8, 145.00, 'Cheese'),
    ('CHE005', 'Gouda Cheese', 'raw_material', 'kg', 10, 125.00, 'Cheese'),
    ('CON001', 'Tomato Sauce', 'raw_material', 'L', 15, 28.00, 'Condiments'),
    ('CON002', 'Mustard', 'raw_material', 'L', 8, 35.00, 'Condiments'),
    ('CON003', 'Mayonnaise', 'raw_material', 'L', 10, 42.00, 'Condiments'),
    ('CON004', 'Sweet Chilli Sauce', 'manufactured_item', 'L', 8, 48.00, 'Condiments'),
    ('CON005', 'BBQ Sauce', 'manufactured_item', 'L', 10, 45.00, 'Condiments'),
    ('CNF001', 'Chocolate Chips', 'raw_material', 'kg', 8, 95.00, 'Confectionery'),
    ('CNF002', 'Marshmallows', 'raw_material', 'kg', 5, 65.00, 'Confectionery'),
    ('CNF003', 'Sprinkles', 'raw_material', 'kg', 3, 120.00, 'Confectionery'),
    ('DAI001', 'Full Cream Milk', 'raw_material', 'L', 50, 18.00, 'Dairy'),
    ('DAI002', 'Fresh Cream', 'raw_material', 'L', 15, 42.00, 'Dairy'),
    ('DAI003', 'Butter', 'raw_material', 'kg', 10, 115.00, 'Dairy'),
    ('DAI004', 'Yoghurt Plain', 'raw_material', 'kg', 10, 55.00, 'Dairy'),
    ('DRY001', 'Rice', 'raw_material', 'kg', 50, 22.00, 'Dry Goods'),
    ('DRY002', 'Pasta Shells', 'raw_material', 'kg', 30, 25.00, 'Dry Goods'),
    ('DRY003', 'Lentils', 'raw_material', 'kg', 15, 28.00, 'Dry Goods'),
    ('DRY004', 'Couscous', 'raw_material', 'kg', 10, 35.00, 'Dry Goods'),
    ('FRZ001', 'Frozen Chips', 'raw_material', 'kg', 40, 28.00, 'Frozen Goods'),
    ('FRZ002', 'Frozen Peas', 'raw_material', 'kg', 20, 24.00, 'Frozen Goods'),
    ('FRZ003', 'Frozen Mixed Veg', 'raw_material', 'kg', 20, 26.00, 'Frozen Goods'),
    ('FRT001', 'Tomatoes', 'raw_material', 'kg', 20, 18.00, 'Fruit'),
    ('FRT002', 'Lemons', 'raw_material', 'kg', 10, 22.00, 'Fruit'),
    ('FRT003', 'Avocados', 'raw_material', 'kg', 8, 45.00, 'Fruit'),
    ('HER001', 'Parsley', 'raw_material', 'kg', 2, 90.00, 'Herbs'),
    ('HER002', 'Coriander', 'raw_material', 'kg', 2, 95.00, 'Herbs'),
    ('HER003', 'Rosemary', 'raw_material', 'kg', 1, 120.00, 'Herbs'),
    ('MEA001', 'Beef Mince', 'raw_material', 'kg', 30, 95.00, 'Meat'),
    ('MEA002', 'Beef Patties', 'portioned_item', 'kg', 25, 110.00, 'Meat'),
    ('MEA003', 'Rump Steak', 'raw_material', 'kg', 20, 180.00, 'Meat'),
    ('OIL001', 'Sunflower Oil', 'raw_material', 'L', 30, 35.00, 'Oils'),
    ('OIL002', 'Olive Oil', 'raw_material', 'L', 10, 120.00, 'Oils'),
    ('PAS001', 'Spaghetti', 'raw_material', 'kg', 25, 24.00, 'Pasta'),
    ('PAS002', 'Penne Pasta', 'raw_material', 'kg', 25, 24.00, 'Pasta'),
    ('POL001', 'Chicken Breast', 'portioned_item', 'kg', 30, 85.00, 'Poultry'),
    ('POL002', 'Chicken Wings', 'portioned_item', 'kg', 25, 65.00, 'Poultry'),
    ('POL003', 'Chicken Whole', 'raw_material', 'kg', 87, 43.50, 'Poultry'),
    ('PRE001', 'Cheese Sauce', 'manufactured_item', 'L', 10, 55.00, 'Prepared Foods'),
    ('PRE002', 'Pepper Sauce', 'manufactured_item', 'L', 10, 52.00, 'Prepared Foods'),
    ('RIC001', 'Basmati Rice', 'raw_material', 'kg', 30, 32.00, 'Rice & Grains'),
    ('RIC002', 'Brown Rice', 'raw_material', 'kg', 20, 30.00, 'Rice & Grains'),
    ('SAU001', 'Tomato Base Sauce', 'raw_material', 'L', 15, 28.00, 'Sauces'),
    ('SAU002', 'Alfredo Sauce', 'manufactured_item', 'L', 10, 45.00, 'Sauces'),
    ('SAU003', 'Mushroom Sauce', 'manufactured_item', 'L', 10, 48.00, 'Sauces'),
    ('SEA001', 'Fresh Oysters', 'portioned_item', 'kg', 10, 100.00, 'Seafood'),
    ('SEA002', 'Mussels', 'portioned_item', 'kg', 8, 85.00, 'Seafood'),
    ('SEA003', 'Calamari', 'portioned_item', 'kg', 12, 120.00, 'Seafood'),
    ('SEA004', 'Prepared Oyster Meat', 'portioned_item', 'kg', 10, 181.82, 'Seafood'),

)
DEMO_STOCK_ITEMS = [
    {
        'code': code,
        'name': name,
        'item_type': item_type,
        'unit': unit,
        'quantity': quantity,
        'cost_per_unit': cost_per_unit,
        'category': category,
        'status': 'Active',
    }
    for code, name, item_type, unit, quantity, cost_per_unit, category
    in _DEMO_STOCK_ROWS
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
                    float(item['quantity']),
                    category_ids[item['category']],
                    int(item['status'] == 'Active'),
                    now,
                    now,
                    user_id,
                    user_id,
                    float(item['cost_per_unit']),
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
