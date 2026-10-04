import sqlite3
import os
import secrets
import sys
from contextvars import ContextVar
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
_CURRENT_COMPANY_ID = ContextVar('current_company_id', default=None)
_CURRENT_USER_ID = ContextVar('current_user_id', default=None)


def set_tenant_context(company_id, user_id):
    _CURRENT_COMPANY_ID.set(company_id)
    _CURRENT_USER_ID.set(user_id)


def clear_tenant_context():
    _CURRENT_COMPANY_ID.set(None)
    _CURRENT_USER_ID.set(None)


def current_company_id():
    return _CURRENT_COMPANY_ID.get()


def current_user_id():
    return _CURRENT_USER_ID.get()

_TENANT_TABLES = (
    'categories', 'users', 'stock_items', 'menu_categories', 'menu_items',
    'menu_item_recipe_lines', 'menu_item_modifier_groups', 'menu_item_modifiers',
    'menu_item_audit', 'menu_item_inventory_transactions',
    'menu_item_inventory_lines', 'manufacturing_transactions',
    'manufacturing_ingredients', 'portioning_sessions',
    'portioning_transactions', 'audit_log', 'stock_movements',
)


def _table_columns(conn, table_name):
    return {row['name'] for row in conn.execute(f'PRAGMA table_info({table_name})')}


def _ensure_column(conn, table_name, column_name, definition):
    if column_name not in _table_columns(conn, table_name):
        conn.execute(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}')


def _rebuild_tenant_unique_tables(conn):
    schemas = {
        'categories': """
            CREATE TABLE categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT,
                created_by INTEGER,
                modified_at TEXT,
                modified_by INTEGER
            )
        """,
        'stock_items': """
            CREATE TABLE stock_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                item_type TEXT NOT NULL DEFAULT 'raw_material'
                    CHECK(item_type IN ('raw_material','manufactured_item','portioned_item')),
                unit TEXT NOT NULL CHECK(unit IN ('kg','L','each')),
                quantity REAL NOT NULL DEFAULT 0,
                category_id INTEGER,
                active INTEGER NOT NULL DEFAULT 1,
                date_created TEXT NOT NULL,
                date_modified TEXT NOT NULL,
                created_by INTEGER,
                modified_by INTEGER,
                unit_cost REAL NOT NULL DEFAULT 0,
                notes TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(category_id) REFERENCES categories(id)
            )
        """,
        'menu_categories': """
            CREATE TABLE menu_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER,
                name TEXT NOT NULL COLLATE NOCASE,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                created_by INTEGER,
                modified_at TEXT NOT NULL,
                modified_by INTEGER,
                FOREIGN KEY(created_by) REFERENCES users(id),
                FOREIGN KEY(modified_by) REFERENCES users(id)
            )
        """,
        'menu_items': """
            CREATE TABLE menu_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER,
                code TEXT NOT NULL COLLATE NOCASE,
                name TEXT NOT NULL,
                item_type TEXT NOT NULL CHECK(item_type IN ('Ordinary Menu Item','Prep Screen Item')),
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
            )
        """,
    }
    indexes = {
        'categories': 'CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_company_name ON categories(company_id, name COLLATE NOCASE)',
        'stock_items': 'CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_items_company_code ON stock_items(company_id, code COLLATE NOCASE)',
        'menu_categories': 'CREATE UNIQUE INDEX IF NOT EXISTS idx_menu_categories_company_name ON menu_categories(company_id, name COLLATE NOCASE)',
        'menu_items': 'CREATE UNIQUE INDEX IF NOT EXISTS idx_menu_items_company_code ON menu_items(company_id, code COLLATE NOCASE)',
    }
    conn.commit()
    conn.execute('PRAGMA foreign_keys = OFF')
    conn.execute('PRAGMA legacy_alter_table = ON')
    try:
        for table_name, create_sql in schemas.items():
            unique_indexes = conn.execute(
                f'PRAGMA index_list({table_name})'
            ).fetchall()
            stock_columns = {
                row['name']: row['type'].upper()
                for row in conn.execute(f'PRAGMA table_info({table_name})')
            }
            stock_numeric_migration = (
                table_name == 'stock_items'
                and any(stock_columns.get(column) != 'REAL'
                        for column in ('quantity', 'unit_cost'))
            )
            has_unique_index = any(index['origin'] == 'u' for index in unique_indexes)
            if not has_unique_index and not stock_numeric_migration:
                conn.execute(indexes[table_name])
                continue
            old_table = f'{table_name}_tenant_migration_old'
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (old_table,),
            ).fetchone():
                conn.execute(f'DROP TABLE {old_table}')
            conn.execute(f'ALTER TABLE {table_name} RENAME TO {old_table}')
            conn.execute(create_sql)
            old_columns = _table_columns(conn, old_table)
            new_columns = _table_columns(conn, table_name)
            columns = [name for name in old_columns if name in new_columns]
            names = ', '.join(f'"{name}"' for name in columns)
            selected_names = ', '.join(
                f'CAST("{name}" AS REAL) AS "{name}"'
                if table_name == 'stock_items' and name in {'quantity', 'unit_cost'}
                else f'"{name}"'
                for name in columns
            )
            conn.execute(
                f'INSERT INTO {table_name} ({names}) '
                f'SELECT {selected_names} FROM {old_table}'
            )
            conn.execute(f'DROP TABLE {old_table}')
            conn.execute(indexes[table_name])
            conn.execute(
                f'CREATE INDEX IF NOT EXISTS idx_{table_name}_company_id '
                f'ON {table_name}(company_id)'
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute('PRAGMA legacy_alter_table = OFF')
        conn.execute('PRAGMA foreign_keys = ON')
    violations = conn.execute('PRAGMA foreign_key_check').fetchall()
    if violations:
        raise sqlite3.IntegrityError(
            f'Tenant schema migration produced {len(violations)} foreign key violation(s).'
        )


def _migrate_company_auth(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            claim_required INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_password_reset_user
            ON password_reset_tokens(user_id, expires_at);

        CREATE TABLE IF NOT EXISTS company_settings (
            company_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY(company_id, key),
            FOREIGN KEY(company_id) REFERENCES companies(id)
        );

        CREATE TABLE IF NOT EXISTS email_delivery_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER,
            user_id INTEGER,
            message_type TEXT NOT NULL,
            recipient TEXT NOT NULL,
            status TEXT NOT NULL,
            error_type TEXT,
            attempted_at TEXT NOT NULL,
            FOREIGN KEY(company_id) REFERENCES companies(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        """
    )
    for table_name in _TENANT_TABLES:
        _ensure_column(conn, table_name, 'company_id', 'INTEGER')
    user_columns = _table_columns(conn, 'users')
    verification_columns_missing = 'email_verified' not in user_columns
    _ensure_column(conn, 'users', 'email', 'TEXT')
    _ensure_column(conn, 'users', 'password_hash', 'TEXT')
    _ensure_column(conn, 'users', 'permissions_version', 'INTEGER NOT NULL DEFAULT 1')
    _ensure_column(conn, 'users', 'email_verified', 'INTEGER NOT NULL DEFAULT 0')
    _ensure_column(conn, 'users', 'verification_token', 'TEXT')
    _ensure_column(conn, 'users', 'verification_token_expiry', 'TEXT')
    _ensure_column(conn, 'users', 'verified_at', 'TEXT')
    _ensure_column(conn, 'users', 'must_change_password', 'INTEGER NOT NULL DEFAULT 0')
    _ensure_column(conn, 'users', 'account_locked', 'INTEGER NOT NULL DEFAULT 0')
    _ensure_column(conn, 'audit_log', 'company_name', "TEXT NOT NULL DEFAULT ''")
    if verification_columns_missing:
        conn.execute(
            'UPDATE users SET email_verified = 1 WHERE password_hash IS NOT NULL'
        )

    companies_count = conn.execute('SELECT COUNT(*) FROM companies').fetchone()[0]
    if not companies_count:
        existing_data = any(
            conn.execute(f'SELECT 1 FROM {table_name} LIMIT 1').fetchone()
            for table_name in ('users', 'categories', 'stock_items', 'menu_items')
        )
        if existing_data:
            now = datetime.utcnow().isoformat(timespec='seconds')
            conn.execute(
                '''INSERT INTO companies
                   (company_name, email, active, created_at, claim_required)
                   VALUES (?, ?, 1, ?, 1)''',
                ('Kitchen Factory Legacy Workspace', 'legacy-workspace@invalid.local', now),
            )

    legacy = conn.execute(
        'SELECT id FROM companies WHERE claim_required = 1 ORDER BY id LIMIT 1'
    ).fetchone()
    if legacy:
        company_id = legacy['id']
        for table_name in _TENANT_TABLES:
            conn.execute(
                f'UPDATE {table_name} SET company_id = ? WHERE company_id IS NULL',
                (company_id,),
            )
        for user in conn.execute(
            'SELECT id, username, display_name, role, active FROM users WHERE company_id = ?',
            (company_id,),
        ).fetchall():
            conn.execute(
                '''UPDATE users SET email = ?, active = 0,
                   role = CASE WHEN lower(role) LIKE '%admin%' THEN 'Company Administrator'
                               WHEN lower(role) LIKE '%manager%' THEN 'Manager'
                               ELSE 'User' END
                   WHERE id = ?''',
                (f'legacy-user-{user["id"]}@invalid.local', user['id']),
            )

    conn.execute('DROP INDEX IF EXISTS idx_users_company_email_unique')
    conn.execute(
        '''CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique
           ON users(lower(email)) WHERE email IS NOT NULL'''
    )
    conn.execute(
        '''CREATE INDEX IF NOT EXISTS idx_users_verification_token
           ON users(verification_token) WHERE verification_token IS NOT NULL'''
    )
    for table_name in _TENANT_TABLES:
        conn.execute(
            f'CREATE INDEX IF NOT EXISTS idx_{table_name}_company_id '
            f'ON {table_name}(company_id)'
        )
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'system_settings'"
    ).fetchone():
        if 'company_id' not in _table_columns(conn, 'system_settings'):
            _ensure_column(conn, 'system_settings', 'company_id', 'INTEGER')
            if legacy:
                conn.execute(
                    'UPDATE system_settings SET company_id = ? WHERE company_id IS NULL',
                    (legacy['id'],),
                )
            conn.execute(
                '''INSERT OR IGNORE INTO company_settings(company_id, key, value)
                   SELECT company_id, key, value FROM system_settings
                   WHERE company_id IS NOT NULL'''
            )


def get_secret_key():
    configured = os.environ.get('KITCHEN_FACTORY_SECRET_KEY')
    if configured:
        if len(configured) < 32:
            raise ValueError('KITCHEN_FACTORY_SECRET_KEY must contain at least 32 characters.')
        return configured
    key_path = DB_PATH.parent / '.kitchen_factory_secret'
    try:
        return key_path.read_text(encoding='ascii').strip()
    except FileNotFoundError:
        key = secrets.token_urlsafe(48)
        try:
            with key_path.open('x', encoding='ascii') as key_file:
                key_file.write(key)
        except FileExistsError:
            return key_path.read_text(encoding='ascii').strip()
        return key


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
                name TEXT NOT NULL,
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
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                item_type TEXT NOT NULL DEFAULT 'raw_material' CHECK(item_type IN ('raw_material','manufactured_item','portioned_item')),
                unit TEXT NOT NULL CHECK(unit IN ('kg','L','each')),
                quantity REAL NOT NULL DEFAULT 0,
                category_id INTEGER,
                active INTEGER NOT NULL DEFAULT 1,
                date_created TEXT NOT NULL,
                date_modified TEXT NOT NULL,
                created_by INTEGER,
                modified_by INTEGER,
                unit_cost REAL NOT NULL DEFAULT 0,
                notes TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(category_id) REFERENCES categories(id)
            );

            CREATE TABLE IF NOT EXISTS menu_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                created_by INTEGER,
                modified_at TEXT NOT NULL,
                modified_by INTEGER,
                FOREIGN KEY(created_by) REFERENCES users(id),
                FOREIGN KEY(modified_by) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS menu_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL COLLATE NOCASE,
                name TEXT NOT NULL,
                item_type TEXT NOT NULL CHECK(item_type IN ('Ordinary Menu Item','Prep Screen Item')),
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
            );

            CREATE TABLE IF NOT EXISTS menu_item_recipe_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                menu_item_id INTEGER NOT NULL,
                item_type TEXT NOT NULL CHECK(item_type IN ('Stock Item','Manufactured Item','Portioned Item')),
                stock_item_id INTEGER NOT NULL,
                quantity TEXT NOT NULL,
                unit_cost TEXT NOT NULL,
                total_cost TEXT NOT NULL,
                FOREIGN KEY(menu_item_id) REFERENCES menu_items(id) ON DELETE CASCADE,
                FOREIGN KEY(stock_item_id) REFERENCES stock_items(id)
            );

            CREATE INDEX IF NOT EXISTS idx_menu_recipe_menu_item
                ON menu_item_recipe_lines(menu_item_id, id);

            CREATE TABLE IF NOT EXISTS menu_item_modifier_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                menu_item_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                required INTEGER NOT NULL DEFAULT 0,
                minimum_selections INTEGER NOT NULL DEFAULT 0,
                maximum_selections INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(menu_item_id) REFERENCES menu_items(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS menu_item_modifiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                modifier_group_id INTEGER NOT NULL,
                modifier_menu_item_id INTEGER NOT NULL,
                price_delta TEXT NOT NULL DEFAULT '0',
                sort_order INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(modifier_group_id) REFERENCES menu_item_modifier_groups(id) ON DELETE CASCADE,
                FOREIGN KEY(modifier_menu_item_id) REFERENCES menu_items(id)
            );

            CREATE TABLE IF NOT EXISTS menu_item_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                menu_item_id INTEGER,
                record_code TEXT NOT NULL,
                record_name TEXT NOT NULL,
                user_id INTEGER,
                action TEXT NOT NULL,
                module TEXT NOT NULL DEFAULT 'Menu Items',
                old_value TEXT,
                new_value TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS menu_item_inventory_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                menu_item_id INTEGER,
                transaction_type TEXT NOT NULL CHECK(transaction_type IN ('sale','refund')),
                quantity TEXT NOT NULL,
                external_reference TEXT,
                original_transaction_id INTEGER,
                user_id INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY(menu_item_id) REFERENCES menu_items(id) ON DELETE SET NULL,
                FOREIGN KEY(original_transaction_id) REFERENCES menu_item_inventory_transactions(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS menu_item_inventory_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id INTEGER NOT NULL,
                stock_item_id INTEGER,
                item_code TEXT NOT NULL,
                item_name TEXT NOT NULL,
                quantity TEXT NOT NULL,
                unit_cost TEXT NOT NULL,
                total_cost TEXT NOT NULL,
                FOREIGN KEY(transaction_id) REFERENCES menu_item_inventory_transactions(id) ON DELETE CASCADE,
                FOREIGN KEY(stock_item_id) REFERENCES stock_items(id) ON DELETE SET NULL
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
                    quantity REAL NOT NULL DEFAULT 0,
                    category_id INTEGER,
                    active INTEGER NOT NULL DEFAULT 1,
                    date_created TEXT NOT NULL,
                    date_modified TEXT NOT NULL,
                    created_by INTEGER,
                    modified_by INTEGER,
                    unit_cost REAL NOT NULL DEFAULT 0,
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
                SELECT id, code, name, item_type, unit,
                       CAST(quantity AS REAL), category_id, active,
                       date_created, date_modified, created_by, modified_by,
                       CAST(unit_cost AS REAL), notes
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
        _migrate_company_auth(conn)
        _rebuild_tenant_unique_tables(conn)
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
        # New companies receive their own seeded categories and settings at registration.
        conn.commit()
    finally:
        conn.close()
