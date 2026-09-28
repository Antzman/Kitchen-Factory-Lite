import sqlite3
import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from settings import SETTING_DEFAULTS


def _database_path():
    configured_dir = os.environ.get("KITCHEN_FACTORY_DATA_DIR")
    if configured_dir:
        data_dir = Path(configured_dir)
    elif getattr(sys, "frozen", False):
        data_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Kitchen Factory"
    else:
        data_dir = Path(__file__).resolve().parent
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "kitchen_factory.db"


DB_PATH = _database_path()


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    database_was_missing = not DB_PATH.exists()
    conn = get_db_connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT,
                created_by INTEGER,
                modified_at TEXT,
                modified_by INTEGER
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                date_created TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS stock_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                item_type TEXT NOT NULL DEFAULT 'raw_material' CHECK(item_type IN ('raw_material','manufactured_item','portioned_item')),
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
            );

            CREATE TABLE IF NOT EXISTS manufacturing_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                output_item_id INTEGER NOT NULL,
                expected_output TEXT NOT NULL,
                actual_output TEXT NOT NULL,
                total_input_quantity TEXT NOT NULL,
                yield_percentage TEXT NOT NULL,
                manufacturing_date TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                notes TEXT,
                total_cost TEXT NOT NULL,
                cost_per_unit TEXT NOT NULL,
                FOREIGN KEY(output_item_id) REFERENCES stock_items(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS manufacturing_ingredients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                quantity TEXT NOT NULL,
                unit_cost TEXT NOT NULL DEFAULT '0',
                total_cost TEXT NOT NULL DEFAULT '0',
                FOREIGN KEY(transaction_id) REFERENCES manufacturing_transactions(id),
                FOREIGN KEY(item_id) REFERENCES stock_items(id)
            );

            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS portioning_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_item_id INTEGER NOT NULL,
                session_date TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                notes TEXT,
                FOREIGN KEY(source_item_id) REFERENCES stock_items(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS portioning_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                source_item_id INTEGER NOT NULL,
                destination_item_id INTEGER,
                original_quantity TEXT NOT NULL,
                quantity_portioned TEXT NOT NULL,
                waste_quantity TEXT NOT NULL,
                yield_percentage TEXT NOT NULL,
                original_cost TEXT NOT NULL,
                adjusted_cost TEXT NOT NULL,
                transaction_date TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                notes TEXT,
                transaction_type TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES portioning_sessions(id),
                FOREIGN KEY(source_item_id) REFERENCES stock_items(id),
                FOREIGN KEY(destination_item_id) REFERENCES stock_items(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT NOT NULL,
                module TEXT NOT NULL,
                record_id TEXT NOT NULL,
                description TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS stock_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                movement_type TEXT NOT NULL,
                quantity TEXT NOT NULL,
                related_transaction TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                user_id INTEGER,
                FOREIGN KEY(item_id) REFERENCES stock_items(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            """
        )
        stock_schema = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'stock_items'"
        ).fetchone()
        if stock_schema and "('kg','L','each')" not in stock_schema['sql'].replace(' ', ''):
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("ALTER TABLE stock_items RENAME TO stock_items_legacy")
            conn.execute(
                """
                CREATE TABLE stock_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    item_type TEXT NOT NULL DEFAULT 'raw_material' CHECK(item_type IN ('raw_material','manufactured_item','portioned_item')),
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
                )
                """
            )
            conn.execute(
                """
                INSERT INTO stock_items
                (id, code, name, item_type, unit, quantity, category_id, active,
                 date_created, date_modified, created_by, modified_by, unit_cost, notes)
                SELECT id, code, name, item_type, unit, quantity, category_id, active,
                       date_created, date_modified, created_by, modified_by, unit_cost, notes
                FROM stock_items_legacy
                """
            )
            conn.execute("DROP TABLE stock_items_legacy")
            conn.execute("PRAGMA foreign_keys = ON")
        # SQLite rewrites child foreign keys when a referenced table is renamed.
        # Restore the original reference after the stock-item table rebuild.
        conn.execute("PRAGMA writable_schema = ON")
        conn.execute(
            "UPDATE sqlite_master SET sql = replace(sql, 'stock_items_legacy', 'stock_items') "
            "WHERE type = 'table' AND sql LIKE '%stock_items_legacy%'"
        )
        conn.execute("PRAGMA writable_schema = OFF")
        conn.execute("PRAGMA integrity_check")
        stock_columns = {row['name'] for row in conn.execute("PRAGMA table_info(stock_items)").fetchall()}
        if 'item_type' not in stock_columns:
            conn.execute("ALTER TABLE stock_items ADD COLUMN item_type TEXT NOT NULL DEFAULT 'raw_material'")
        if 'notes' not in stock_columns:
            conn.execute("ALTER TABLE stock_items ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
        ingredient_columns = {row['name'] for row in conn.execute("PRAGMA table_info(manufacturing_ingredients)").fetchall()}
        if 'unit_cost' not in ingredient_columns:
            conn.execute("ALTER TABLE manufacturing_ingredients ADD COLUMN unit_cost TEXT NOT NULL DEFAULT '0'")
        if 'total_cost' not in ingredient_columns:
            conn.execute("ALTER TABLE manufacturing_ingredients ADD COLUMN total_cost TEXT NOT NULL DEFAULT '0'")
        conn.executemany(
            "INSERT OR IGNORE INTO system_settings(key, value) VALUES (?, ?)",
            list(SETTING_DEFAULTS.items()),
        )
        # Migrate the former appearance controls to the validated theme model.
        conn.execute(
            "INSERT OR REPLACE INTO system_settings(key, value) "
            "SELECT 'appearance_mode', CASE value WHEN 'dark' THEN 'dark' ELSE 'light' END "
            "FROM system_settings WHERE key IN ('appearance_mode', 'appearance_system_default') "
            "ORDER BY CASE key WHEN 'appearance_mode' THEN 0 ELSE 1 END LIMIT 1"
        )
        conn.execute(
            "INSERT OR REPLACE INTO system_settings(key, value) "
            "SELECT 'appearance_colour_scheme', CASE value "
            "WHEN '#2563eb' THEN 'kitchen_blue' WHEN 'kitchen_blue' THEN 'kitchen_blue' "
            "ELSE 'kitchen_green' END FROM system_settings "
            "WHERE key IN ('appearance_colour_scheme', 'appearance_accent') "
            "ORDER BY CASE key WHEN 'appearance_colour_scheme' THEN 0 ELSE 1 END LIMIT 1"
        )
        conn.execute("DELETE FROM system_settings WHERE key IN ('appearance_system_default', 'appearance_accent', 'appearance_density', 'appearance_theme', 'appearance_font_size')")
        conn.commit()
    finally:
        conn.close()
    return database_was_missing


def seed_data():
    conn = get_db_connection()
    try:
        default_categories = [
            'Meat', 'Poultry', 'Seafood', 'Dairy', 'Cheese', 'Bakery', 'Bread', 'Pasta',
            'Rice & Grains', 'Vegetables', 'Fruit', 'Herbs', 'Spices', 'Sauces', 'Condiments',
            'Oils', 'Vinegar', 'Dry Goods', 'Baking Ingredients', 'Confectionery', 'Frozen Goods',
            'Prepared Foods', 'Beverages', 'Other'
        ]
        if conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
            now = datetime.utcnow().isoformat(timespec='seconds')
            for name in default_categories:
                conn.execute(
                    "INSERT INTO categories(name, description, active, created_at, created_by, modified_at, modified_by) VALUES (?, ?, 1, ?, NULL, ?, NULL)",
                    (name, 'Default category', now, now)
                )

        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            now = datetime.utcnow().isoformat(timespec='seconds')
            rows = [
                ('admin', 'System Admin', 'Administrator', 1, now),
                ('manager', 'Kitchen Manager', 'Manager', 1, now),
                ('user', 'Kitchen User', 'User', 1, now),
            ]
            conn.executemany(
                "INSERT INTO users(username, display_name, role, active, date_created) VALUES (?, ?, ?, ?, ?)",
                rows,
            )

        if conn.execute("SELECT COUNT(*) FROM stock_items").fetchone()[0] == 0:
            user_id = conn.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()['id']
            category_id = conn.execute("SELECT id FROM categories WHERE name = 'Prepared Foods'").fetchone()['id']
            now = datetime.utcnow().isoformat(timespec='seconds')
            items = [
                ('MILK-001', 'Milk', 'kg', '5.000', category_id, 1, now, now, user_id, user_id, '0.00'),
                ('CHEESE-001', 'Cheddar Cheese', 'kg', '2.000', category_id, 1, now, now, user_id, user_id, '0.00'),
                ('BUTTER-001', 'Butter', 'kg', '0.500', category_id, 1, now, now, user_id, user_id, '0.00'),
                ('SALT-001', 'Salt', 'kg', '0.050', category_id, 1, now, now, user_id, user_id, '0.00'),
                ('PEPPER-001', 'Pepper', 'kg', '0.025', category_id, 1, now, now, user_id, user_id, '0.00'),
                ('SAUCE-001', 'Pepper Sauce', 'kg', '0.000', category_id, 1, now, now, user_id, user_id, '0.00'),
            ]
            conn.executemany(
                "INSERT INTO stock_items(code, name, unit, quantity, category_id, active, date_created, date_modified, created_by, modified_by, unit_cost) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                items,
            )

        conn.commit()
    finally:
        conn.close()
