from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from db import get_db_connection
from settings import SETTING_CHOICES, SETTING_DEFAULTS, setting_bool, setting_int, setting_value

ALLOWED_UNITS = {'kg', 'L', 'each'}
ALLOWED_ITEM_TYPES = {'raw_material', 'manufactured_item', 'portioned_item'}


def q2(value):
    return Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def decimalize(value):
    return Decimal(str(value))


def calculate_yield_loss(original_quantity, usable_quantity, original_total_cost):
    original = decimalize(original_quantity)
    usable = decimalize(usable_quantity)
    cost = decimalize(original_total_cost)
    if original <= 0:
        raise ValueError('Original quantity must be greater than zero.')
    if usable <= 0:
        raise ValueError('Usable quantity must be greater than zero.')
    if usable > original:
        raise ValueError('Usable quantity cannot exceed original quantity.')
    if cost < 0:
        raise ValueError('Original total cost cannot be negative.')
    waste = original - usable
    yield_pct = (usable / original) * Decimal('100')
    adjusted_cost = cost / usable if usable > 0 else Decimal('0')
    return {
        'waste_quantity': waste,
        'yield_percentage': yield_pct,
        'adjusted_cost_per_unit': adjusted_cost,
    }


def get_user_by_username(username):
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    conn.close()
    return row


def get_setting(key, default=''):
    conn = get_db_connection()
    row = conn.execute('SELECT value FROM system_settings WHERE key = ?', (key,)).fetchone()
    conn.close()
    value = row['value'] if row else SETTING_DEFAULTS.get(key, default)
    choices = SETTING_CHOICES.get(key)
    return value if not choices or value in choices else SETTING_DEFAULTS.get(key, default)


def get_settings():
    conn = get_db_connection()
    try:
        rows = conn.execute('SELECT key, value FROM system_settings').fetchall()
        values = dict(SETTING_DEFAULTS)
        values.update({row['key']: row['value'] for row in rows if row['key'] in SETTING_DEFAULTS})
        for key, choices in SETTING_CHOICES.items():
            if values.get(key) not in choices:
                values[key] = SETTING_DEFAULTS[key]
        return values
    finally:
        conn.close()


def update_settings(values):
    unknown = set(values) - set(SETTING_DEFAULTS)
    if unknown:
        raise ValueError(f'Unknown setting(s): {", ".join(sorted(unknown))}')
    invalid = {
        key: value for key, value in values.items()
        if key in SETTING_CHOICES and str(value) not in SETTING_CHOICES[key]
    }
    if invalid:
        raise ValueError(f'Invalid setting value for {next(iter(invalid))}.')
    conn = get_db_connection()
    try:
        for key, value in values.items():
            conn.execute(
                'INSERT INTO system_settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value',
                (key, setting_value(key, value)),
            )
        conn.commit()
    finally:
        conn.close()


def set_setting(key, value):
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO system_settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value',
        (key, str(value)),
    )
    conn.commit()
    conn.close()


def list_users(include_inactive=True):
    conn = get_db_connection()
    query = 'SELECT * FROM users ORDER BY display_name'
    if not include_inactive:
        query = 'SELECT * FROM users WHERE active = 1 ORDER BY display_name'
    rows = conn.execute(query).fetchall()
    conn.close()
    return rows


def create_user(username, display_name, role, active=True):
    if not username.strip() or not display_name.strip() or not role.strip():
        raise ValueError('Username, display name and role are required.')
    conn = get_db_connection()
    try:
        if conn.execute('SELECT 1 FROM users WHERE lower(username)=lower(?)', (username.strip(),)).fetchone():
            raise ValueError('Username already exists.')
        now = datetime.utcnow().isoformat(timespec='seconds')
        cur = conn.execute(
            'INSERT INTO users(username, display_name, role, active, date_created) VALUES (?, ?, ?, ?, ?)',
            (username.strip(), display_name.strip(), role.strip(), 1 if active else 0, now),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_user(user_id, username, display_name, role, active=True):
    if not username.strip() or not display_name.strip() or not role.strip():
        raise ValueError('Username, display name and role are required.')
    conn = get_db_connection()
    try:
        if not conn.execute('SELECT 1 FROM users WHERE id=?', (user_id,)).fetchone():
            raise ValueError('User not found.')
        if conn.execute('SELECT 1 FROM users WHERE lower(username)=lower(?) AND id != ?', (username.strip(), user_id)).fetchone():
            raise ValueError('Username already exists.')
        conn.execute('UPDATE users SET username=?, display_name=?, role=?, active=? WHERE id=?',
                     (username.strip(), display_name.strip(), role.strip(), 1 if active else 0, user_id))
        conn.commit()
    finally:
        conn.close()


def list_categories():
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM categories WHERE active = 1 ORDER BY name').fetchall()
    conn.close()
    return rows


def create_category(name, description=''):
    if not name or not name.strip():
        raise ValueError('Category name is required.')
    conn = get_db_connection()
    try:
        existing = conn.execute('SELECT 1 FROM categories WHERE lower(name) = lower(?)', (name.strip(),)).fetchone()
        if existing:
            raise ValueError('Category already exists.')
        now = datetime.utcnow().isoformat(timespec='seconds')
        cur = conn.execute(
            'INSERT INTO categories(name, description, active, created_at, created_by, modified_at, modified_by) VALUES (?, ?, 1, ?, NULL, ?, NULL)',
            (name.strip(), description.strip(), now, now)
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_category(category_id, name, description=''):
    if not name or not name.strip():
        raise ValueError('Category name is required.')
    conn = get_db_connection()
    try:
        if conn.execute('SELECT 1 FROM categories WHERE lower(name)=lower(?) AND id != ?',
                        (name.strip(), category_id)).fetchone():
            raise ValueError('Category already exists.')
        if not conn.execute('SELECT 1 FROM categories WHERE id=?', (category_id,)).fetchone():
            raise ValueError('Category not found.')
        conn.execute('UPDATE categories SET name=?, description=?, modified_at=? WHERE id=?',
                     (name.strip(), description.strip(), datetime.utcnow().isoformat(timespec='seconds'), category_id))
        conn.commit()
    finally:
        conn.close()


def set_category_active(category_id, active):
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT name FROM categories WHERE id=?', (category_id,)).fetchone()
        if not row:
            raise ValueError('Category not found.')
        conn.execute('UPDATE categories SET active=?, modified_at=? WHERE id=?',
                     (1 if active else 0, datetime.utcnow().isoformat(timespec='seconds'), category_id))
        conn.commit()
        return row['name']
    finally:
        conn.close()


def list_stock_items():
    conn = get_db_connection()
    rows = conn.execute(
        '''SELECT si.*, c.name AS category_name FROM stock_items si LEFT JOIN categories c ON c.id = si.category_id ORDER BY si.name'''
    ).fetchall()
    conn.close()
    items = []
    for row in rows:
        item = dict(row)
        item['total_cost'] = q2(Decimal(str(item['quantity'])) * Decimal(str(item['unit_cost'])))
        items.append(item)
    return items


def stock_item_report(search='', category='', item_type='', unit='', status='',
                      sort='code', direction='asc', page=1, per_page=25):
    sort_columns = {
        'code': 'si.code',
        'name': 'si.name',
        'type': 'si.item_type',
        'category': 'c.name',
        'quantity': 'CAST(si.quantity AS DECIMAL)',
        'unit_cost': 'CAST(si.unit_cost AS DECIMAL)',
        'total_cost': '(CAST(si.quantity AS DECIMAL) * CAST(si.unit_cost AS DECIMAL))',
        'status': 'si.active',
    }
    sort_expression = sort_columns.get(sort, sort_columns['code'])
    order = 'DESC' if direction.lower() == 'desc' else 'ASC'
    clauses = []
    params = []
    if search:
        clauses.append('(si.code LIKE ? OR si.name LIKE ? OR c.name LIKE ?)')
        term = f'%{search}%'
        params.extend([term, term, term])
    if category:
        clauses.append('c.name = ?')
        params.append(category)
    if item_type:
        clauses.append('si.item_type = ?')
        params.append(item_type)
    if unit:
        clauses.append('si.unit = ?')
        params.append(unit)
    if status in ('active', 'inactive'):
        clauses.append('si.active = ?')
        params.append(1 if status == 'active' else 0)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ''
    conn = get_db_connection()
    try:
        base = f'''FROM stock_items si
                   LEFT JOIN categories c ON c.id = si.category_id
                   {where}'''
        total_count = conn.execute(f'SELECT COUNT(*) {base}', params).fetchone()[0]
        raw_rows = conn.execute(
            f'''SELECT si.*, c.name AS category_name
                {base}
                ORDER BY {sort_expression} {order}, si.id ASC
                LIMIT ? OFFSET ?''',
            params + [per_page, max(0, (page - 1) * per_page)],
        ).fetchall()
        rows = []
        for row in raw_rows:
            item = dict(row)
            item['total_cost'] = q2(Decimal(str(item['quantity'])) * Decimal(str(item['unit_cost'])))
            rows.append(item)
        all_rows = conn.execute(f'SELECT si.*, c.name AS category_name {base}', params).fetchall()
        total_value = sum(
            (Decimal(str(row['quantity'])) * Decimal(str(row['unit_cost'])) for row in all_rows),
            Decimal('0'),
        )
        totals = {
            'stock_items': total_count,
            'active_items': sum(1 for row in all_rows if row['active']),
            'inactive_items': sum(1 for row in all_rows if not row['active']),
            'inventory_value': q2(total_value),
        }
        return rows, totals, total_count
    finally:
        conn.close()


def get_stock_item(item_id):
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM stock_items WHERE id = ?', (item_id,)).fetchone()
    conn.close()
    return row


def set_stock_item_active(item_id, active, modified_by):
    if active not in (0, 1):
        raise ValueError('Stock item status must be active or inactive.')
    conn = get_db_connection()
    try:
        current = conn.execute('SELECT code, notes FROM stock_items WHERE id = ?', (item_id,)).fetchone()
        if not current:
            raise ValueError('Stock item not found.')
        if active == 0 and not (current['notes'] or '').strip():
            raise ValueError('Add a note in the stock item edit screen before marking it inactive.')
        now = datetime.utcnow().isoformat(timespec='seconds')
        conn.execute(
            'UPDATE stock_items SET active = ?, date_modified = ?, modified_by = ? WHERE id = ?',
            (active, now, modified_by, item_id),
        )
        conn.commit()
        return current['code']
    finally:
        conn.close()


def create_stock_item(code, name, unit, quantity, category_id, created_by, unit_cost='0', item_type='raw_material'):
    if not code or not name or not unit:
        raise ValueError('Code, name and unit are required.')
    if item_type not in ALLOWED_ITEM_TYPES:
        raise ValueError('Stock item type must be raw material, manufactured item, or portioned item.')
    if unit not in ALLOWED_UNITS:
        raise ValueError('Unit must be kg, L, or each.')
    try:
        qty = Decimal(str(quantity))
    except InvalidOperation:
        raise ValueError('Quantity must be numeric.')
    if qty < 0:
        raise ValueError('Quantity cannot be negative.')
    try:
        cost = q2(unit_cost)
    except (InvalidOperation, ValueError):
        raise ValueError('Cost per unit must be numeric.')
    if cost < 0:
        raise ValueError('Cost per unit cannot be negative.')
    conn = get_db_connection()
    try:
        if conn.execute('SELECT 1 FROM stock_items WHERE lower(code) = lower(?)', (code.strip(),)).fetchone():
            raise ValueError('Stock code already exists.')
        now = datetime.utcnow().isoformat(timespec='seconds')
        cur = conn.execute(
            'INSERT INTO stock_items(code, name, item_type, unit, quantity, category_id, active, date_created, date_modified, created_by, modified_by, unit_cost) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)',
            (code.strip(), name.strip(), item_type, unit, str(qty), category_id, now, now, created_by, created_by, str(cost))
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_stock_item(item_id, code, name, unit, quantity, category_id, modified_by, active=True, unit_cost='0', notes='', item_type='raw_material'):
    if not code or not name or not unit:
        raise ValueError('Code, name and unit are required.')
    if item_type not in ALLOWED_ITEM_TYPES:
        raise ValueError('Stock item type must be raw material, manufactured item, or portioned item.')
    if unit not in ALLOWED_UNITS:
        raise ValueError('Unit must be kg, L, or each.')
    try:
        qty = Decimal(str(quantity))
    except InvalidOperation:
        raise ValueError('Quantity must be numeric.')
    if qty < 0:
        raise ValueError('Quantity cannot be negative.')
    try:
        cost = q2(unit_cost)
    except (InvalidOperation, ValueError):
        raise ValueError('Cost per unit must be numeric.')
    if cost < 0:
        raise ValueError('Cost per unit cannot be negative.')
    conn = get_db_connection()
    try:
        current = conn.execute('SELECT * FROM stock_items WHERE id = ?', (item_id,)).fetchone()
        if not current:
            raise ValueError('Stock item not found.')
        if current['code'].lower() != code.strip().lower():
            existing = conn.execute('SELECT 1 FROM stock_items WHERE lower(code) = lower(?) AND id != ?', (code.strip(), item_id)).fetchone()
            if existing:
                raise ValueError('Another stock item already uses this code.')
        now = datetime.utcnow().isoformat(timespec='seconds')
        conn.execute(
            'UPDATE stock_items SET code = ?, name = ?, item_type = ?, unit = ?, quantity = ?, category_id = ?, active = ?, date_modified = ?, modified_by = ?, unit_cost = ?, notes = ? WHERE id = ?',
            (code.strip(), name.strip(), item_type, unit, str(qty), category_id, 1 if active else 0, now, modified_by, str(cost), notes.strip(), item_id)
        )
        conn.commit()
        return item_id
    finally:
        conn.close()


def validate_import_rows(rows):
    valid_rows = []
    errors = []
    seen = set()
    for idx, row in enumerate(rows, start=1):
        code = (row.get('Stock Item Code') or '').strip()
        name = (row.get('Stock Item Name') or '').strip()
        unit = (row.get('Unit') or '').strip()
        quantity = row.get('Quantity') or ''
        category = (row.get('Category') or '').strip()
        if not code:
            errors.append(f'Row {idx}: missing stock code')
            continue
        if code.lower() in seen:
            errors.append(f'Row {idx}: duplicate stock code {code}')
            continue
        seen.add(code.lower())
        if not name:
            errors.append(f'Row {idx}: missing stock name for {code}')
            continue
        if unit not in ALLOWED_UNITS:
            errors.append(f'Row {idx}: invalid unit {unit!r} for {code}')
            continue
        try:
            qty = Decimal(str(quantity))
        except InvalidOperation:
            errors.append(f'Row {idx}: invalid numeric quantity for {code}')
            continue
        if qty < 0:
            errors.append(f'Row {idx}: quantity cannot be negative for {code}')
            continue
        if not category:
            errors.append(f'Row {idx}: missing category for {code}')
            continue
        valid_rows.append({'code': code, 'name': name, 'unit': unit, 'quantity': str(qty), 'category': category})
    return valid_rows, errors


def parse_csv(text):
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError('CSV file is empty or missing headers.')
    required = {'Stock Item Code', 'Stock Item Name', 'Unit', 'Quantity', 'Category'}
    fields = {str(f).strip() for f in reader.fieldnames}
    if not required.issubset(fields):
        raise ValueError('CSV must include Stock Item Code, Stock Item Name, Unit, Quantity, Category.')
    rows = []
    for row in reader:
        if row and any((value or '').strip() for value in row.values()):
            rows.append({k.strip(): (v or '').strip() for k, v in row.items()})
    return rows


def import_stock_items(rows, user_id):
    conn = get_db_connection()
    try:
        accepted = []
        rejected = []
        now = datetime.utcnow().isoformat(timespec='seconds')
        for row in rows:
            category = conn.execute('SELECT id FROM categories WHERE lower(name) = lower(?) AND active = 1', (row['category'],)).fetchone()
            if not category:
                rejected.append({**row, 'error': 'Category does not exist or is inactive'})
                continue
            if conn.execute('SELECT 1 FROM stock_items WHERE lower(code) = lower(?)', (row['code'],)).fetchone():
                rejected.append({**row, 'error': 'Duplicate stock code found'})
                continue
            cur = conn.execute(
                'INSERT INTO stock_items(code, name, unit, quantity, category_id, active, date_created, date_modified, created_by, modified_by, unit_cost) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)',
                (row['code'], row['name'], row['unit'], row['quantity'], category['id'], now, now, user_id, user_id, '0.00')
            )
            accepted.append(row)
        conn.commit()
        return accepted, rejected
    finally:
        conn.close()


def create_manufacturing_transaction(output_item_id, ingredient_rows, expected_output, actual_output, user_id,
                                     notes='', calculator_mode=None, confirmation=False):
    if not output_item_id:
        raise ValueError('Output stock item is required.')
    try:
        expected = Decimal(str(expected_output))
        actual = Decimal(str(actual_output))
    except InvalidOperation:
        raise ValueError('Manufactured output must be numeric.')
    if expected <= 0 or actual <= 0:
        raise ValueError('Expected and actual outputs must be greater than zero.')

    conn = get_db_connection()
    try:
        output = conn.execute('SELECT * FROM stock_items WHERE id = ?', (output_item_id,)).fetchone()
        if not output:
            raise ValueError('Output stock item does not exist.')
        if output['item_type'] != 'manufactured_item':
            raise ValueError('Manufacturing output must be a Manufactured Item stock type.')
        allow_negative = setting_bool('allow_negative_stock', get_setting('allow_negative_stock'))
        calculator_mode = setting_bool('calculator_mode', get_setting('calculator_mode'))
        if setting_bool('manufacturing_require_notes', get_setting('manufacturing_require_notes')) and not notes.strip():
            raise ValueError('Manufacturing notes are required.')
        if setting_bool('manufacturing_require_confirmation', get_setting('manufacturing_require_confirmation')) and not confirmation:
            raise ValueError('Manufacturing confirmation is required.')
        ingredient_entries = []
        total_input = Decimal('0')
        total_cost = Decimal('0')
        seen_ids = set()
        for ingredient in ingredient_rows:
            item_id = ingredient.get('item_id')
            qty = ingredient.get('quantity')
            if not item_id:
                raise ValueError('Every ingredient must reference a stock item.')
            if item_id in seen_ids:
                raise ValueError('A stock item may only be used once as an ingredient.')
            seen_ids.add(item_id)
            item = conn.execute('SELECT * FROM stock_items WHERE id = ?', (item_id,)).fetchone()
            if not item:
                raise ValueError('Ingredient stock item not found.')
            try:
                q = Decimal(str(qty))
            except InvalidOperation:
                raise ValueError(f'Ingredient quantity for {item["name"]} is invalid.')
            if q <= 0:
                raise ValueError(f'Ingredient quantity for {item["name"]} must be greater than zero.')
            if item['unit'] != output['unit']:
                raise ValueError(f'Ingredient {item["name"]} uses {item["unit"]}, output uses {output["unit"]}.')
            if not allow_negative and not calculator_mode and Decimal(item['quantity']) < q:
                raise ValueError(f'Insufficient stock for {item["name"]}. Available: {item["quantity"]} {item["unit"]}.')
            total_input += q
            ingredient_cost = q * Decimal(str(item['unit_cost']))
            total_cost += ingredient_cost
            ingredient_entries.append((item, q, ingredient_cost))
        if not ingredient_entries:
            raise ValueError('At least one ingredient is required.')

        bypass_stock_update = calculator_mode
        yield_pct = (actual / expected) * Decimal('100')
        cost_per_unit = total_cost / actual if actual > 0 else Decimal('0')
        now = datetime.utcnow().isoformat(timespec='seconds')
        cur = conn.execute(
            'INSERT INTO manufacturing_transactions(output_item_id, expected_output, actual_output, total_input_quantity, yield_percentage, manufacturing_date, user_id, notes, total_cost, cost_per_unit) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (output_item_id, str(expected), str(actual), str(total_input), str(yield_pct), now, user_id, notes, str(q2(total_cost)), str(q2(cost_per_unit)))
        )
        transaction_id = cur.lastrowid
        for item, q, ingredient_cost in ingredient_entries:
            conn.execute(
                'INSERT INTO manufacturing_ingredients(transaction_id, item_id, quantity, unit_cost, total_cost) VALUES (?, ?, ?, ?, ?)',
                (transaction_id, item['id'], str(q), str(item['unit_cost']), str(q2(ingredient_cost))),
            )
            if not bypass_stock_update:
                conn.execute('UPDATE stock_items SET quantity = quantity - ?, date_modified = ? WHERE id = ?', (str(q), now, item['id']))
        if not bypass_stock_update:
            conn.execute('UPDATE stock_items SET quantity = quantity + ?, date_modified = ? WHERE id = ?', (str(actual), now, output_item_id))
            if setting_bool('manufacturing_auto_cost', get_setting('manufacturing_auto_cost')):
                conn.execute('UPDATE stock_items SET unit_cost = ? WHERE id = ?', (str(q2(cost_per_unit)), output_item_id))
            conn.execute('INSERT INTO stock_movements(item_id, movement_type, quantity, related_transaction, notes, created_at, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)', (output_item_id, 'manufacturing_output', str(actual), f'MFG-{transaction_id}', notes, now, user_id))
        conn.commit()
        return {'transaction_id': transaction_id, 'yield_percentage': yield_pct, 'total_cost': total_cost, 'cost_per_unit': cost_per_unit}
    finally:
        conn.close()


def create_bulk_portioning(source_item_id, destination_item_id, quantity_portioned, user_id, notes='', waste_reason=''):
    if source_item_id == destination_item_id:
        raise ValueError('Source and destination stock items must be different.')
    try:
        qty = Decimal(str(quantity_portioned))
    except InvalidOperation:
        raise ValueError('Portioned quantity must be numeric.')
    if qty <= 0:
        raise ValueError('Portioned quantity must be greater than zero.')
    if setting_bool('portioning_require_waste_reason', get_setting('portioning_require_waste_reason')) and not waste_reason.strip():
        raise ValueError('A waste reason is required for portioning.')

    conn = get_db_connection()
    try:
        calculator_mode = setting_bool('calculator_mode', get_setting('calculator_mode'))
        source = conn.execute('SELECT * FROM stock_items WHERE id = ?', (source_item_id,)).fetchone()
        dest = conn.execute('SELECT * FROM stock_items WHERE id = ?', (destination_item_id,)).fetchone()
        if not source or not dest:
            raise ValueError('Source and destination stock items must exist.')
        if dest['item_type'] != 'portioned_item':
            raise ValueError('Portioning destination must be a Portioned Item stock type.')
        if source['unit'] != dest['unit']:
            raise ValueError('Source and destination stock items must use the same unit.')
        if not setting_bool('allow_negative_stock', get_setting('allow_negative_stock')) and not calculator_mode and Decimal(source['quantity']) < qty:
            raise ValueError(f'Insufficient stock in {source["name"]}. Available: {source["quantity"]}.')
        now = datetime.utcnow().isoformat(timespec='seconds')
        transaction_notes = notes.strip()
        if waste_reason.strip():
            transaction_notes = f'{transaction_notes}\nWaste reason: {waste_reason.strip()}'.strip()
        session_id = conn.execute('INSERT INTO portioning_sessions(source_item_id, session_date, user_id, notes) VALUES (?, ?, ?, ?)', (source_item_id, now, user_id, notes)).lastrowid
        conn.execute(
            'INSERT INTO portioning_transactions(session_id, source_item_id, destination_item_id, original_quantity, quantity_portioned, waste_quantity, yield_percentage, original_cost, adjusted_cost, transaction_date, user_id, notes, transaction_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (session_id, source_item_id, destination_item_id, source['quantity'], str(qty), '0.00', '100.00', '0.00', '0.00', now, user_id, transaction_notes, 'bulk')
        )
        if not calculator_mode:
            conn.execute('UPDATE stock_items SET quantity = quantity - ? WHERE id = ?', (str(qty), source_item_id))
            conn.execute('UPDATE stock_items SET quantity = quantity + ? WHERE id = ?', (str(qty), destination_item_id))
        conn.commit()
        return {'session_id': session_id}
    finally:
        conn.close()


def create_yield_loss_portioning(source_item_id, destination_item_id, original_quantity, usable_quantity, original_total_cost, user_id, notes='', waste_reason=''):
    try:
        original = Decimal(str(original_quantity))
        usable = Decimal(str(usable_quantity))
        cost = Decimal(str(original_total_cost))
    except InvalidOperation:
        raise ValueError('Original quantity, usable quantity and cost must be numeric.')
    if original <= 0 or usable <= 0:
        raise ValueError('Original and usable quantities must be greater than zero.')
    if usable > original:
        raise ValueError('Usable quantity cannot exceed original quantity.')
    if cost < 0:
        raise ValueError('Original total cost cannot be negative.')
    if setting_bool('portioning_require_waste_reason', get_setting('portioning_require_waste_reason')) and not waste_reason.strip():
        raise ValueError('A waste reason is required for portioning.')

    conn = get_db_connection()
    try:
        calculator_mode = setting_bool('calculator_mode', get_setting('calculator_mode'))
        source = conn.execute('SELECT * FROM stock_items WHERE id = ?', (source_item_id,)).fetchone()
        if not source:
            raise ValueError('Source stock item does not exist.')
        if destination_item_id:
            dest = conn.execute('SELECT * FROM stock_items WHERE id = ?', (destination_item_id,)).fetchone()
            if not dest:
                raise ValueError('Destination stock item does not exist.')
            if dest['item_type'] != 'portioned_item':
                raise ValueError('Portioning destination must be a Portioned Item stock type.')
            if source['unit'] != dest['unit']:
                raise ValueError('Source and destination stock items must use the same unit.')
        if not setting_bool('allow_negative_stock', get_setting('allow_negative_stock')) and not calculator_mode and Decimal(source['quantity']) < original:
            raise ValueError(f'Insufficient stock in {source["name"]}. Available: {source["quantity"]}.')
        result = calculate_yield_loss(original, usable, cost)
        try:
            minimum = Decimal(str(get_setting('portioning_minimum_yield', '0') or '0'))
        except InvalidOperation:
            minimum = Decimal('0')
        result['yield_warning'] = minimum > 0 and result['yield_percentage'] < minimum
        now = datetime.utcnow().isoformat(timespec='seconds')
        transaction_notes = notes.strip()
        if waste_reason.strip():
            transaction_notes = f'{transaction_notes}\nWaste reason: {waste_reason.strip()}'.strip()
        session_id = conn.execute('INSERT INTO portioning_sessions(source_item_id, session_date, user_id, notes) VALUES (?, ?, ?, ?)', (source_item_id, now, user_id, notes)).lastrowid
        conn.execute(
            'INSERT INTO portioning_transactions(session_id, source_item_id, destination_item_id, original_quantity, quantity_portioned, waste_quantity, yield_percentage, original_cost, adjusted_cost, transaction_date, user_id, notes, transaction_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (session_id, source_item_id, destination_item_id or source_item_id, str(original), str(usable), str(result['waste_quantity']), str(result['yield_percentage']), str(cost), str(result['adjusted_cost_per_unit']), now, user_id, transaction_notes, 'yield_loss')
        )
        if not calculator_mode:
            conn.execute('UPDATE stock_items SET quantity = quantity - ? WHERE id = ?', (str(original), source_item_id))
            if destination_item_id:
                conn.execute('UPDATE stock_items SET quantity = quantity + ? WHERE id = ?', (str(usable), destination_item_id))
        conn.commit()
        return {'session_id': session_id, 'adjusted_cost_per_unit': result['adjusted_cost_per_unit'], 'yield_warning': result['yield_warning']}
    finally:
        conn.close()


def list_recent_portioning(limit=10):
    conn = get_db_connection()
    rows = conn.execute(
        '''SELECT pt.*, s.name AS source_name, d.name AS destination_name, u.display_name AS user_name FROM portioning_transactions pt LEFT JOIN stock_items s ON s.id = pt.source_item_id LEFT JOIN stock_items d ON d.id = pt.destination_item_id LEFT JOIN users u ON u.id = pt.user_id ORDER BY pt.transaction_date DESC LIMIT ?''',
        (limit,)
    ).fetchall()
    conn.close()
    return rows


def dashboard_metrics():
    conn = get_db_connection()
    metrics = {
        'total_stock_items': conn.execute('SELECT COUNT(*) FROM stock_items').fetchone()[0],
        'manufacturing_transactions': conn.execute('SELECT COUNT(*) FROM manufacturing_transactions').fetchone()[0],
        'portioning_transactions': conn.execute('SELECT COUNT(*) FROM portioning_transactions').fetchone()[0],
        'recent_activity': conn.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0],
    }
    conn.close()
    return metrics


def audit_entries(limit=20):
    conn = get_db_connection()
    retention = setting_int('audit_retention_days', get_setting('audit_retention_days'))
    query = '''SELECT al.*, u.display_name AS user_name FROM audit_log al
               LEFT JOIN users u ON u.id = al.user_id'''
    params = []
    if retention > 0:
        query += " WHERE al.created_at >= datetime('now', ?)"
        params.append(f'-{retention} days')
    query += ' ORDER BY al.created_at DESC LIMIT ?'
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return rows


def list_manufacturing_history(limit=20):
    conn = get_db_connection()
    rows = conn.execute(
        '''SELECT mt.*, o.name AS output_name, u.display_name AS user_name FROM manufacturing_transactions mt LEFT JOIN stock_items o ON o.id = mt.output_item_id LEFT JOIN users u ON u.id = mt.user_id ORDER BY mt.manufacturing_date DESC LIMIT ?''',
        (limit,)
    ).fetchall()
    conn.close()
    return rows


def add_audit(user_id, action, module, record_id, description):
    if not setting_bool('audit_enabled', get_setting('audit_enabled')):
        return
    level = get_setting('audit_level', 'standard')
    if level == 'minimal' and action not in {'MANUFACTURING CREATED', 'PORTIONING CREATED', 'PORTIONING COMPLETED',
                                             'STOCK ITEM CREATED', 'STOCK ITEM IMPORTED', 'SETTING UPDATED'}:
        return
    if level == 'detailed':
        description = f'{description} [module={module}; record={record_id}]'
    conn = get_db_connection()
    now = datetime.utcnow().isoformat(timespec='seconds')
    conn.execute(
        'INSERT INTO audit_log(user_id, action, module, record_id, description, created_at) VALUES (?, ?, ?, ?, ?, ?)',
        (user_id, action, module, str(record_id), description, now)
    )
    conn.commit()
    conn.close()
