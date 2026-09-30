from __future__ import annotations

import csv
import io
import json
import re
import secrets
import logging
from hashlib import sha256
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from db import current_company_id, current_user_id, get_db_connection
from settings import SETTING_CHOICES, SETTING_DEFAULTS, setting_bool, setting_int, setting_value
from werkzeug.security import check_password_hash, generate_password_hash

ALLOWED_UNITS = {'kg', 'L', 'each'}
ALLOWED_ITEM_TYPES = {'raw_material', 'manufactured_item', 'portioned_item'}
USER_ROLES = {'Company Administrator', 'Manager', 'User'}
STOCK_CATEGORIES = (
    'Meat', 'Poultry', 'Seafood', 'Dairy', 'Cheese', 'Bakery', 'Bread', 'Pasta',
    'Rice & Grains', 'Vegetables', 'Fruit', 'Herbs', 'Spices', 'Sauces',
    'Condiments', 'Oils', 'Vinegar', 'Dry Goods', 'Baking Ingredients',
    'Confectionery', 'Frozen Goods', 'Prepared Foods', 'Beverages', 'Other',
)
logger = logging.getLogger(__name__)


def _tenant_id(company_id=None):
    company_id = company_id if company_id is not None else current_company_id()
    if company_id is None:
        raise ValueError('A company context is required for this operation.')
    return int(company_id)


def _valid_email(email):
    email = (email or '').strip()
    return bool(
        len(email) <= 254 and
        re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", email)
    )


def _validate_password(password):
    if not password:
        raise ValueError('Password is required.')
    if len(password) < 12:
        raise ValueError('Password must be at least 12 characters long.')
    if len(password) > 1024:
        raise ValueError('Password must not exceed 1024 characters.')


def _record_security_audit(conn, company_id, user_id, action, record_id, description):
    company = conn.execute(
        'SELECT company_name FROM companies WHERE id = ?', (company_id,)
    ).fetchone()
    conn.execute(
        '''INSERT INTO audit_log
           (company_id, company_name, user_id, action, module, record_id, description, created_at)
           VALUES (?, ?, ?, ?, 'Authentication', ?, ?, ?)''',
        (company_id, company['company_name'] if company else '',
         user_id, action, str(record_id), description,
         datetime.utcnow().isoformat(timespec='seconds')),
    )


def register_company(company_name, email, password, confirmation):
    company_name = (company_name or '').strip()
    email = (email or '').strip().casefold()
    if not company_name:
        raise ValueError('Company name is required.')
    if not _valid_email(email):
        raise ValueError('Enter a valid email address.')
    _validate_password(password)
    if not confirmation:
        raise ValueError('Password confirmation is required.')
    if password != confirmation:
        raise ValueError('Passwords do not match.')

    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        legacy = conn.execute(
            'SELECT * FROM companies WHERE claim_required = 1 ORDER BY id LIMIT 1'
        ).fetchone()
        if conn.execute(
            'SELECT 1 FROM companies WHERE lower(email) = lower(?)', (email,)
        ).fetchone() and not (legacy and legacy['email'].casefold() == email):
            raise ValueError('An account already exists for that company email.')
        if conn.execute(
            'SELECT 1 FROM users WHERE lower(email) = lower(?)', (email,)
        ).fetchone():
            raise ValueError('An account already exists for that email address.')
        now = datetime.utcnow().isoformat(timespec='seconds')
        if legacy:
            company_id = legacy['id']
            conn.execute(
                '''UPDATE companies SET company_name = ?, email = ?, claim_required = 0
                   WHERE id = ?''',
                (company_name, email, company_id),
            )
        else:
            company_id = conn.execute(
                '''INSERT INTO companies(company_name, email, active, created_at)
                   VALUES (?, ?, 1, ?)''',
                (company_name, email, now),
            ).lastrowid
        category_rows = [
            (company_id, name, 'Default category', now, now)
            for name in STOCK_CATEGORIES
        ]
        conn.executemany(
            '''INSERT OR IGNORE INTO categories
               (company_id, name, description, active, created_at, modified_at)
               VALUES (?, ?, ?, 1, ?, ?)''',
            category_rows,
        )
        now = datetime.utcnow().isoformat(timespec='seconds')
        for category_name in ('Food', 'Beverages'):
            conn.execute(
                '''INSERT OR IGNORE INTO menu_categories
                   (company_id, name, active, created_at, modified_at)
                   VALUES (?, ?, 1, ?, ?)''',
                (company_id, category_name, now, now),
            )
        for key, value in SETTING_DEFAULTS.items():
            conn.execute(
                '''INSERT OR IGNORE INTO company_settings(company_id, key, value)
                   VALUES (?, ?, ?)''',
                (company_id, key, value),
            )
        verification_token = secrets.token_urlsafe(32)
        token_hash = sha256(verification_token.encode('utf-8')).hexdigest()
        verification_expiry = (
            datetime.utcnow().replace(microsecond=0) + timedelta(hours=24)
        ).isoformat()
        user_id = conn.execute(
            '''INSERT INTO users
               (company_id, username, email, password_hash, display_name, role, active,
                date_created, email_verified, verification_token, verification_token_expiry)
               VALUES (?, ?, ?, ?, ?, 'Company Administrator', 1, ?, 0, ?, ?)''',
            (company_id, f'{company_id}:{email}', email, generate_password_hash(password),
             company_name, now, token_hash, verification_expiry),
        ).lastrowid
        _record_security_audit(
            conn, company_id, user_id, 'COMPANY REGISTERED', company_id,
            f'{company_name} registered.',
        )
        _record_security_audit(
            conn, company_id, user_id, 'USER CREATED', user_id,
            f'Company Administrator account created for {email}.',
        )
        conn.commit()
        return {
            **dict(get_user_by_id(user_id)),
            'verification_token': verification_token,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_user_by_id(user_id):
    if user_id is None:
        return None
    conn = get_db_connection()
    try:
        return conn.execute(
            '''SELECT u.*, c.company_name, c.email AS company_email, c.active AS company_active
               FROM users u JOIN companies c ON c.id = u.company_id
               WHERE u.id = ?''',
            (user_id,),
        ).fetchone()
    finally:
        conn.close()


def get_user_by_email(email):
    conn = get_db_connection()
    try:
        return conn.execute(
            '''SELECT u.*, c.company_name, c.active AS company_active
               FROM users u JOIN companies c ON c.id = u.company_id
               WHERE lower(u.email) = lower(?)''',
            ((email or '').strip(),),
        ).fetchone()
    finally:
        conn.close()


def authenticate_user(email, password):
    user = get_user_by_email(email)
    if not user or not user['active'] or not user['company_active'] or not user['password_hash']:
        return None
    if not check_password_hash(user['password_hash'], password or ''):
        return None
    if not user['email_verified']:
        return None
    return user


def unverified_login_account(email, password):
    user = get_user_by_email(email)
    if (
        not user or not user['active'] or not user['company_active']
        or not user['password_hash'] or user['email_verified']
    ):
        return None
    return user if check_password_hash(user['password_hash'], password or '') else None


def create_email_verification_token(user_id):
    token = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        updated = conn.execute(
            '''UPDATE users SET verification_token = ?, verification_token_expiry = ?
               WHERE id = ? AND active = 1 AND email_verified = 0''',
            (sha256(token.encode('utf-8')).hexdigest(),
             (now.replace(microsecond=0) + timedelta(hours=24)).isoformat(), user_id),
        )
        if updated.rowcount != 1:
            conn.rollback()
            return None
        conn.commit()
        return token
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def verify_email_token(token):
    token_hash = sha256((token or '').encode('utf-8')).hexdigest()
    now = datetime.utcnow().isoformat(timespec='seconds')
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        user = conn.execute(
            '''SELECT u.*, c.company_name, c.active AS company_active
               FROM users u JOIN companies c ON c.id = u.company_id
               WHERE u.verification_token = ?''',
            (token_hash,),
        ).fetchone()
        if not user:
            _record_security_audit(
                conn, None, None, 'VERIFICATION FAILED', 'email-verification',
                'Email verification failed for an unknown or invalid token.',
            )
            conn.commit()
            return 'invalid', None
        if user['email_verified']:
            conn.rollback()
            return 'used', user['id']
        if not user['verification_token_expiry'] or user['verification_token_expiry'] <= now:
            _record_security_audit(
                conn, user['company_id'], user['id'], 'VERIFICATION TOKEN EXPIRED',
                user['id'], f'Expired email verification token used for {user["email"]}.',
            )
            _record_security_audit(
                conn, user['company_id'], user['id'], 'VERIFICATION FAILED',
                user['id'], 'Email verification failed because its token expired.',
            )
            conn.execute(
                '''UPDATE users SET verification_token = NULL,
                   verification_token_expiry = NULL WHERE id = ?''',
                (user['id'],),
            )
            conn.commit()
            return 'expired', user['id']
        if not user['active'] or not user['company_active']:
            _record_security_audit(
                conn, user['company_id'], user['id'], 'VERIFICATION FAILED',
                user['id'], 'Email verification failed for an inactive account.',
            )
            conn.commit()
            return 'inactive', user['id']
        updated = conn.execute(
            '''UPDATE users SET email_verified = 1, verified_at = ?,
               verification_token = NULL, verification_token_expiry = NULL
               WHERE id = ? AND email_verified = 0 AND verification_token = ?''',
            (now, user['id'], token_hash),
        )
        if updated.rowcount != 1:
            conn.rollback()
            return 'invalid', None
        _record_security_audit(
            conn, user['company_id'], user['id'], 'EMAIL VERIFIED', user['id'],
            f'Email verified for {user["email"]}.',
        )
        conn.commit()
        return 'verified', user['id']
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def record_email_delivery(company_id, user_id, message_type, recipient, status,
                          error_type=None, resent=False):
    conn = get_db_connection()
    try:
        conn.execute(
            '''INSERT INTO email_delivery_log
               (company_id, user_id, message_type, recipient, status, error_type, attempted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (company_id, user_id, message_type, recipient, status, error_type,
             datetime.utcnow().isoformat(timespec='seconds')),
        )
        if message_type == 'verification':
            action = (
                'VERIFICATION EMAIL RESENT' if resent else 'VERIFICATION EMAIL SENT'
            ) if status == 'sent' else (
                'VERIFICATION EMAIL RESEND FAILED' if resent else 'VERIFICATION EMAIL FAILED'
            )
        else:
            action = 'PASSWORD RESET EMAIL SENT' if status == 'sent' else 'PASSWORD RESET EMAIL FAILED'
        _record_security_audit(
            conn, company_id, user_id, action, user_id or recipient,
            f'{message_type.replace("_", " ").title()} email delivery status: {status}.',
        )
        conn.commit()
    finally:
        conn.close()


def create_password_reset_token(email):
    user = get_user_by_email(email)
    if not user or not user['active'] or not user['company_active']:
        return None
    token = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute(
            '''UPDATE password_reset_tokens SET used_at = ?
               WHERE user_id = ? AND used_at IS NULL''',
            (now.isoformat(timespec='seconds'), user['id']),
        )
        conn.execute(
            '''INSERT INTO password_reset_tokens
               (user_id, token_hash, expires_at, created_at)
               VALUES (?, ?, ?, ?)''',
            (user['id'], sha256(token.encode('utf-8')).hexdigest(),
             (now.replace(microsecond=0) + timedelta(hours=1)).isoformat(),
             now.isoformat(timespec='seconds')),
        )
        conn.commit()
        return token
    finally:
        conn.close()


def reset_password(token, password, confirmation):
    _validate_password(password)
    if not confirmation:
        raise ValueError('Password confirmation is required.')
    if password != confirmation:
        raise ValueError('Passwords do not match.')
    token_hash = sha256((token or '').encode('utf-8')).hexdigest()
    now = datetime.utcnow().isoformat(timespec='seconds')
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        reset = conn.execute(
            '''SELECT prt.*, u.company_id, u.email
               FROM password_reset_tokens prt
               JOIN users u ON u.id = prt.user_id
               JOIN companies c ON c.id = u.company_id
               WHERE prt.token_hash = ? AND prt.used_at IS NULL
                 AND prt.expires_at > ? AND u.active = 1 AND c.active = 1''',
            (token_hash, now),
        ).fetchone()
        if not reset:
            raise ValueError('This password reset link is invalid or has expired.')
        updated = conn.execute(
            '''UPDATE password_reset_tokens SET used_at = ?
               WHERE id = ? AND used_at IS NULL AND expires_at > ?''',
            (now, reset['id'], now),
        )
        if updated.rowcount != 1:
            raise ValueError('This password reset link is invalid or has expired.')
        conn.execute(
            'UPDATE users SET password_hash = ? WHERE id = ?',
            (generate_password_hash(password), reset['user_id']),
        )
        _record_security_audit(
            conn, reset['company_id'], reset['user_id'], 'PASSWORD RESET',
            reset['user_id'], f'Password reset for {reset["email"]}.',
        )
        conn.commit()
        return reset['user_id']
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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
    try:
        company_id = current_company_id()
        if company_id is None:
            return None
        return conn.execute(
            '''SELECT * FROM users WHERE company_id = ?
               AND (username = ? OR lower(email) = lower(?))''',
            (company_id, username, username),
        ).fetchone()
    finally:
        conn.close()


def get_setting(key, default=''):
    conn = get_db_connection()
    try:
        company_id = current_company_id()
        if company_id is not None:
            row = conn.execute(
                'SELECT value FROM company_settings WHERE company_id = ? AND key = ?',
                (company_id, key),
            ).fetchone()
        else:
            row = conn.execute(
                'SELECT value FROM system_settings WHERE key = ?', (key,)
            ).fetchone()
    finally:
        conn.close()
    value = row['value'] if row else SETTING_DEFAULTS.get(key, default)
    choices = SETTING_CHOICES.get(key)
    return value if not choices or value in choices else SETTING_DEFAULTS.get(key, default)


def get_settings():
    conn = get_db_connection()
    try:
        company_id = current_company_id()
        if company_id is None:
            rows = conn.execute('SELECT key, value FROM system_settings').fetchall()
        else:
            rows = conn.execute(
                'SELECT key, value FROM company_settings WHERE company_id = ?',
                (company_id,),
            ).fetchall()
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
        company_id = _tenant_id()
        for key, value in values.items():
            conn.execute(
                '''INSERT INTO company_settings(company_id, key, value) VALUES (?, ?, ?)
                   ON CONFLICT(company_id, key) DO UPDATE SET value = excluded.value''',
                (company_id, key, setting_value(key, value)),
            )
        conn.commit()
    finally:
        conn.close()


def set_setting(key, value):
    conn = get_db_connection()
    try:
        conn.execute(
            '''INSERT INTO company_settings(company_id, key, value) VALUES (?, ?, ?)
               ON CONFLICT(company_id, key) DO UPDATE SET value = excluded.value''',
            (_tenant_id(), key, str(value)),
        )
        conn.commit()
    finally:
        conn.close()


def list_users(include_inactive=True):
    conn = get_db_connection()
    company_id = _tenant_id()
    query = 'SELECT * FROM users WHERE company_id = ? ORDER BY display_name'
    params = [company_id]
    if not include_inactive:
        query = 'SELECT * FROM users WHERE company_id = ? AND active = 1 ORDER BY display_name'
    try:
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


def create_user(email, display_name, role, password, confirmation, active=True):
    email = (email or '').strip().casefold()
    display_name = (display_name or '').strip()
    company_id = _tenant_id()
    if not _valid_email(email) or not display_name:
        raise ValueError('A valid email address and name are required.')
    if role not in USER_ROLES:
        raise ValueError('Select a valid user role.')
    _validate_password(password)
    if not confirmation:
        raise ValueError('Password confirmation is required.')
    if password != confirmation:
        raise ValueError('Passwords do not match.')
    conn = get_db_connection()
    try:
        if conn.execute(
            'SELECT 1 FROM users WHERE lower(email) = lower(?)',
            (email,),
        ).fetchone():
            raise ValueError('A user with that email address already exists.')
        now = datetime.utcnow().isoformat(timespec='seconds')
        conn.execute('BEGIN IMMEDIATE')
        user_id = conn.execute(
            '''INSERT INTO users
               (company_id, username, email, password_hash, display_name, role, active, date_created)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (company_id, f'{company_id}:{email}', email, generate_password_hash(password),
             display_name, role, int(bool(active)), now),
        ).lastrowid
        _record_security_audit(
            conn, company_id, current_user_id(), 'USER CREATED', user_id,
            f'Created user {email}.',
        )
        conn.commit()
        return user_id
    finally:
        conn.close()


def update_user(user_id, email, display_name, role, active=True):
    email = (email or '').strip().casefold()
    display_name = (display_name or '').strip()
    company_id = _tenant_id()
    if not _valid_email(email) or not display_name:
        raise ValueError('A valid email address and name are required.')
    if role not in USER_ROLES:
        raise ValueError('Select a valid user role.')
    conn = get_db_connection()
    try:
        current = conn.execute(
            'SELECT * FROM users WHERE id = ? AND company_id = ?',
            (user_id, company_id),
        ).fetchone()
        if not current:
            raise ValueError('User not found.')
        if conn.execute(
            'SELECT 1 FROM users WHERE lower(email)=lower(?) AND id != ?',
            (email, user_id),
        ).fetchone():
            raise ValueError('A user with that email address already exists.')
        if current['role'] == 'Company Administrator' and (
            role != 'Company Administrator' or not active
        ):
            admin_count = conn.execute(
                '''SELECT COUNT(*) FROM users
                   WHERE company_id = ? AND role = 'Company Administrator'
                     AND active = 1 AND id != ?''',
                (company_id, user_id),
            ).fetchone()[0]
            if not admin_count:
                raise ValueError('The company must retain at least one active administrator.')
        if not active:
            conn.execute(
                '''UPDATE password_reset_tokens SET used_at = ?
                   WHERE user_id = ? AND used_at IS NULL''',
                (datetime.utcnow().isoformat(timespec='seconds'), user_id),
            )
        email_changed = current['email'].casefold() != email.casefold()
        conn.execute(
            '''UPDATE users SET username = ?, email = ?, display_name = ?, role = ?, active = ?,
               email_verified = CASE WHEN ? THEN 0 ELSE email_verified END,
               verified_at = CASE WHEN ? THEN NULL ELSE verified_at END,
               verification_token = CASE WHEN ? THEN NULL ELSE verification_token END,
               verification_token_expiry = CASE WHEN ? THEN NULL
                   ELSE verification_token_expiry END
               WHERE id = ? AND company_id = ?''',
            (f'{company_id}:{email}', email, display_name, role, int(bool(active)),
             int(email_changed), int(email_changed), int(email_changed), int(email_changed),
             user_id, company_id),
        )
        if bool(current['active']) != bool(active):
            action = 'USER ACTIVATED' if active else 'USER DISABLED'
            _record_security_audit(
                conn, company_id, current_user_id(), action, user_id,
                f'{action.title()}: {email}.',
            )
        conn.commit()
    finally:
        conn.close()


def administrator_reset_user_password(user_id, password, confirmation):
    _validate_password(password)
    if not confirmation:
        raise ValueError('Password confirmation is required.')
    if password != confirmation:
        raise ValueError('Passwords do not match.')
    company_id = _tenant_id()
    conn = get_db_connection()
    try:
        user = conn.execute(
            'SELECT email FROM users WHERE id = ? AND company_id = ?',
            (user_id, company_id),
        ).fetchone()
        if not user:
            raise ValueError('User not found.')
        conn.execute(
            '''UPDATE password_reset_tokens SET used_at = ?
               WHERE user_id = ? AND used_at IS NULL''',
            (datetime.utcnow().isoformat(timespec='seconds'), user_id),
        )
        conn.execute(
            'UPDATE users SET password_hash = ? WHERE id = ? AND company_id = ?',
            (generate_password_hash(password), user_id, company_id),
        )
        _record_security_audit(
            conn, company_id, current_user_id(), 'PASSWORD RESET', user_id,
            f'Administrator reset the password for {user["email"]}.',
        )
        conn.commit()
    finally:
        conn.close()


def list_categories():
    conn = get_db_connection()
    try:
        return conn.execute(
            'SELECT * FROM categories WHERE company_id = ? AND active = 1 ORDER BY name',
            (_tenant_id(),),
        ).fetchall()
    finally:
        conn.close()


def create_category(name, description=''):
    if not name or not name.strip():
        raise ValueError('Category name is required.')
    conn = get_db_connection()
    try:
        company_id = _tenant_id()
        existing = conn.execute(
            'SELECT 1 FROM categories WHERE company_id = ? AND lower(name) = lower(?)',
            (company_id, name.strip()),
        ).fetchone()
        if existing:
            raise ValueError('Category already exists.')
        now = datetime.utcnow().isoformat(timespec='seconds')
        cur = conn.execute(
            '''INSERT INTO categories
               (company_id, name, description, active, created_at, created_by, modified_at, modified_by)
               VALUES (?, ?, ?, 1, ?, ?, ?, ?)''',
            (company_id, name.strip(), description.strip(), now, current_user_id(), now, current_user_id())
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
        company_id = _tenant_id()
        if conn.execute(
            'SELECT 1 FROM categories WHERE company_id = ? AND lower(name)=lower(?) AND id != ?',
            (company_id, name.strip(), category_id),
        ).fetchone():
            raise ValueError('Category already exists.')
        if not conn.execute(
            'SELECT 1 FROM categories WHERE id = ? AND company_id = ?',
            (category_id, company_id),
        ).fetchone():
            raise ValueError('Category not found.')
        conn.execute(
            '''UPDATE categories SET name = ?, description = ?, modified_at = ?, modified_by = ?
               WHERE id = ? AND company_id = ?''',
            (name.strip(), description.strip(), datetime.utcnow().isoformat(timespec='seconds'),
             current_user_id(), category_id, company_id),
        )
        conn.commit()
    finally:
        conn.close()


def set_category_active(category_id, active):
    conn = get_db_connection()
    try:
        company_id = _tenant_id()
        row = conn.execute(
            'SELECT name FROM categories WHERE id = ? AND company_id = ?',
            (category_id, company_id),
        ).fetchone()
        if not row:
            raise ValueError('Category not found.')
        conn.execute(
            '''UPDATE categories SET active = ?, modified_at = ?, modified_by = ?
               WHERE id = ? AND company_id = ?''',
            (1 if active else 0, datetime.utcnow().isoformat(timespec='seconds'),
             current_user_id(), category_id, company_id),
        )
        conn.commit()
        return row['name']
    finally:
        conn.close()


MENU_ITEM_TYPES = {'Ordinary Menu Item', 'Prep Screen Item'}
MENU_ITEM_TYPE_LABELS = {
    'Ordinary Menu Item': 'Ordinary Type',
    'Prep Screen Item': 'Prep Screen Item',
}
RECIPE_ITEM_TYPES = {
    'Stock Item': 'raw_material',
    'Manufactured Item': 'manufactured_item',
    'Portioned Item': 'portioned_item',
}


def _normalize_menu_item_type(value):
    value = (value or '').strip()
    if value == 'Ordinary Type':
        return 'Ordinary Menu Item'
    return value


def _menu_item_snapshot(row):
    return {
        'code': row['code'],
        'name': row['name'],
        'item_type': row['item_type'],
        'category_id': row['category_id'],
        'selling_price': row['selling_price'],
        'active': row['active'],
    }


def _write_menu_audit(conn, menu_item_id, record_code, record_name, user_id,
                      action, old_value, new_value):
    company_id = _tenant_id()
    now = datetime.utcnow().isoformat(timespec='seconds')
    conn.execute(
        '''INSERT INTO menu_item_audit
           (company_id, menu_item_id, record_code, record_name, user_id, action, module,
            old_value, new_value, created_at)
           VALUES (?, ?, ?, ?, ?, ?, 'Menu Items', ?, ?, ?)''',
        (company_id, menu_item_id, record_code, record_name, user_id, action,
         json.dumps(old_value, sort_keys=True, default=str) if old_value is not None else None,
         json.dumps(new_value, sort_keys=True, default=str) if new_value is not None else None,
         now),
    )
    if setting_bool('audit_enabled', get_setting('audit_enabled')):
        conn.execute(
            '''INSERT INTO audit_log
               (company_id, company_name, user_id, action, module, record_id, description, created_at)
               VALUES (?, (SELECT company_name FROM companies WHERE id = ?), ?, ?, 'Menu Items', ?, ?, ?)''',
            (company_id, company_id, user_id, action, str(menu_item_id if menu_item_id is not None else record_code),
             f'{action.title()} {record_code} — {record_name}', now),
        )


def list_menu_categories(include_inactive=True):
    conn = get_db_connection()
    try:
        where = 'company_id = ?' if include_inactive else 'company_id = ? AND active = 1'
        return conn.execute(
            f'SELECT * FROM menu_categories WHERE {where} ORDER BY name',
            (_tenant_id(),),
        ).fetchall()
    finally:
        conn.close()


def create_menu_category(name, user_id=None):
    name = (name or '').strip()
    if not name:
        raise ValueError('Menu category name is required.')
    conn = get_db_connection()
    try:
        company_id = _tenant_id()
        if conn.execute(
            'SELECT 1 FROM menu_categories WHERE company_id = ? AND name = ? COLLATE NOCASE',
            (company_id, name),
        ).fetchone():
            raise ValueError('Menu category already exists.')
        now = datetime.utcnow().isoformat(timespec='seconds')
        cur = conn.execute(
            '''INSERT INTO menu_categories
               (company_id, name, active, created_at, created_by, modified_at, modified_by)
               VALUES (?, ?, 1, ?, ?, ?, ?)''',
            (company_id, name, now, user_id, now, user_id),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_menu_category(category_id, name, user_id=None):
    name = (name or '').strip()
    if not name:
        raise ValueError('Menu category name is required.')
    conn = get_db_connection()
    try:
        company_id = _tenant_id()
        current = conn.execute(
            'SELECT * FROM menu_categories WHERE id = ? AND company_id = ?',
            (category_id, company_id),
        ).fetchone()
        if not current:
            raise ValueError('Menu category not found.')
        duplicate = conn.execute(
            'SELECT 1 FROM menu_categories WHERE company_id = ? AND name = ? COLLATE NOCASE AND id != ?',
            (company_id, name, category_id),
        ).fetchone()
        if duplicate:
            raise ValueError('Menu category already exists.')
        now = datetime.utcnow().isoformat(timespec='seconds')
        conn.execute(
            'UPDATE menu_categories SET name = ?, modified_at = ?, modified_by = ? WHERE id = ? AND company_id = ?',
            (name, now, user_id, category_id, company_id),
        )
        conn.commit()
    finally:
        conn.close()


def set_menu_category_active(category_id, active, user_id=None):
    if active not in (0, 1, False, True):
        raise ValueError('Menu category status must be active or inactive.')
    conn = get_db_connection()
    try:
        company_id = _tenant_id()
        current = conn.execute(
            'SELECT * FROM menu_categories WHERE id = ? AND company_id = ?',
            (category_id, company_id),
        ).fetchone()
        if not current:
            raise ValueError('Menu category not found.')
        now = datetime.utcnow().isoformat(timespec='seconds')
        conn.execute(
            'UPDATE menu_categories SET active = ?, modified_at = ?, modified_by = ? WHERE id = ? AND company_id = ?',
            (int(bool(active)), now, user_id, category_id, company_id),
        )
        conn.commit()
        return current['name']
    finally:
        conn.close()


def delete_menu_category(category_id):
    conn = get_db_connection()
    try:
        company_id = _tenant_id()
        category = conn.execute(
            'SELECT name FROM menu_categories WHERE id = ? AND company_id = ?',
            (category_id, company_id),
        ).fetchone()
        if not category:
            raise ValueError('Menu category not found.')
        if conn.execute(
            'SELECT 1 FROM menu_items WHERE category_id = ? AND company_id = ? LIMIT 1',
            (category_id, company_id),
        ).fetchone():
            raise ValueError('This category is assigned to menu items. Reassign them before deleting it.')
        conn.execute(
            'DELETE FROM menu_categories WHERE id = ? AND company_id = ?',
            (category_id, company_id),
        )
        conn.commit()
        return category['name']
    finally:
        conn.close()


def list_menu_items(search=''):
    conn = get_db_connection()
    try:
        company_id = _tenant_id()
        params = []
        where = 'WHERE mi.company_id = ?'
        params.append(company_id)
        if search:
            where += ' AND (mi.code LIKE ? OR mi.name LIKE ? OR mc.name LIKE ?)'
            term = f'%{search.strip()}%'
            params.extend([term, term, term])
        rows = conn.execute(
            f'''SELECT mi.*, mc.name AS category_name,
                       rl.quantity AS recipe_quantity, si.unit_cost AS recipe_unit_cost
                FROM menu_items mi
                JOIN menu_categories mc ON mc.id = mi.category_id AND mc.company_id = mi.company_id
                LEFT JOIN menu_item_recipe_lines rl ON rl.menu_item_id = mi.id
                LEFT JOIN stock_items si ON si.id = rl.stock_item_id AND si.company_id = mi.company_id
                {where}
                ORDER BY mi.name COLLATE NOCASE, mi.id, rl.id''',
            params,
        ).fetchall()
        items = []
        by_id = {}
        for row in rows:
            item = by_id.get(row['id'])
            if item is None:
                item = dict(row)
                item['cost_price'] = Decimal('0')
                by_id[row['id']] = item
                items.append(item)
            if row['recipe_quantity'] is not None:
                item['cost_price'] += q2(
                    Decimal(str(row['recipe_quantity'])) *
                    Decimal(str(row['recipe_unit_cost']))
                )
        for item in items:
            item['item_type'] = MENU_ITEM_TYPE_LABELS[item['item_type']]
            item['cost_price'] = q2(item['cost_price'])
            item['selling_price'] = q2(item['selling_price'])
            item['gross_profit'] = q2(item['selling_price'] - item['cost_price'])
            item['gross_profit_percentage'] = (
                item['gross_profit'] / item['selling_price'] * Decimal('100')
                if item['selling_price'] else Decimal('0')
            )
        return items
    finally:
        conn.close()


def get_menu_item(menu_item_id):
    items = list_menu_items()
    return next((item for item in items if item['id'] == menu_item_id), None)


def get_menu_item_recipe(menu_item_id):
    conn = get_db_connection()
    try:
        company_id = _tenant_id()
        rows = conn.execute(
            '''SELECT rl.*, si.code AS item_code, si.name AS item_name,
                      si.unit, si.active AS item_active, si.unit_cost AS current_unit_cost
               FROM menu_item_recipe_lines rl
               JOIN stock_items si ON si.id = rl.stock_item_id AND si.company_id = ?
               JOIN menu_items mi ON mi.id = rl.menu_item_id AND mi.company_id = ?
               WHERE rl.menu_item_id = ?
               ORDER BY rl.id''',
            (company_id, company_id, menu_item_id),
        ).fetchall()
        lines = []
        for row in rows:
            line = dict(row)
            line['unit_cost'] = Decimal(str(line['current_unit_cost']))
            line['total_cost'] = q2(
                Decimal(str(line['quantity'])) * line['unit_cost']
            )
            lines.append(line)
        return lines
    finally:
        conn.close()


def create_menu_item(code, name, item_type, category_id, selling_price, user_id):
    code = (code or '').strip()
    name = (name or '').strip()
    if not code or not name:
        raise ValueError('Menu item code and name are required.')
    item_type = _normalize_menu_item_type(item_type)
    if item_type not in MENU_ITEM_TYPES:
        raise ValueError('Select a valid menu item type.')
    try:
        price = q2(selling_price)
    except (InvalidOperation, ValueError):
        raise ValueError('Selling price must be a valid amount.')
    if not price.is_finite() or price < 0:
        raise ValueError('Selling price cannot be negative.')
    conn = get_db_connection()
    try:
        company_id = _tenant_id()
        category = conn.execute(
            'SELECT id FROM menu_categories WHERE id = ? AND company_id = ? AND active = 1',
            (category_id, company_id),
        ).fetchone()
        if not category:
            raise ValueError('Select an active menu category.')
        if conn.execute(
            'SELECT 1 FROM menu_items WHERE company_id = ? AND code = ? COLLATE NOCASE',
            (company_id, code),
        ).fetchone():
            raise ValueError('Menu item code already exists.')
        now = datetime.utcnow().isoformat(timespec='seconds')
        cur = conn.execute(
            '''INSERT INTO menu_items
               (company_id, code, name, item_type, category_id, selling_price, active,
                date_created, date_modified, created_by, modified_by)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)''',
            (company_id, code, name, item_type, category_id, str(price), now, now, user_id, user_id),
        )
        menu_item_id = cur.lastrowid
        _write_menu_audit(
            conn, menu_item_id, code, name, user_id, 'MENU ITEM CREATED', None,
            {'code': code, 'name': name, 'item_type': item_type,
             'category_id': category_id, 'selling_price': str(price), 'active': True},
        )
        conn.commit()
        return menu_item_id
    finally:
        conn.close()


def update_menu_item(menu_item_id, code, name, item_type, category_id,
                     selling_price, active, user_id):
    code = (code or '').strip()
    name = (name or '').strip()
    if not code or not name:
        raise ValueError('Menu item code and name are required.')
    item_type = _normalize_menu_item_type(item_type)
    if item_type not in MENU_ITEM_TYPES:
        raise ValueError('Select a valid menu item type.')
    try:
        price = q2(selling_price)
    except (InvalidOperation, ValueError):
        raise ValueError('Selling price must be a valid amount.')
    if not price.is_finite() or price < 0:
        raise ValueError('Selling price cannot be negative.')
    conn = get_db_connection()
    try:
        company_id = _tenant_id()
        current = conn.execute(
            'SELECT * FROM menu_items WHERE id = ? AND company_id = ?',
            (menu_item_id, company_id),
        ).fetchone()
        if not current:
            raise ValueError('Menu item not found.')
        if conn.execute(
            'SELECT 1 FROM menu_items WHERE company_id = ? AND code = ? COLLATE NOCASE AND id != ?',
            (company_id, code, menu_item_id),
        ).fetchone():
            raise ValueError('Another menu item already uses this code.')
        category = conn.execute(
            'SELECT id FROM menu_categories WHERE id = ? AND company_id = ? AND (active = 1 OR id = ?)',
            (category_id, company_id, current['category_id']),
        ).fetchone()
        if not category:
            raise ValueError('Select an active menu category.')
        old_value = _menu_item_snapshot(current)
        now = datetime.utcnow().isoformat(timespec='seconds')
        conn.execute(
            '''UPDATE menu_items
               SET code = ?, name = ?, item_type = ?, category_id = ?,
                   selling_price = ?, active = ?, date_modified = ?, modified_by = ?
               WHERE id = ? AND company_id = ?''',
            (code, name, item_type, category_id, str(price), int(bool(active)),
             now, user_id, menu_item_id, company_id),
        )
        new_value = {
            'code': code, 'name': name, 'item_type': item_type,
            'category_id': category_id, 'selling_price': str(price),
            'active': bool(active),
        }
        if old_value != new_value:
            _write_menu_audit(
                conn, menu_item_id, code, name, user_id, 'MENU ITEM UPDATED',
                old_value, new_value,
            )
        conn.commit()
    finally:
        conn.close()


def delete_menu_item(menu_item_id, user_id):
    conn = get_db_connection()
    try:
        company_id = _tenant_id()
        current = conn.execute(
            'SELECT * FROM menu_items WHERE id = ? AND company_id = ?',
            (menu_item_id, company_id),
        ).fetchone()
        if not current:
            raise ValueError('Menu item not found.')
        if conn.execute(
            'SELECT 1 FROM menu_item_inventory_transactions WHERE menu_item_id = ? AND company_id = ? LIMIT 1',
            (menu_item_id, company_id),
        ).fetchone():
            raise ValueError('This menu item has sales history and cannot be deleted. Mark it inactive instead.')
        if conn.execute(
            '''SELECT 1 FROM menu_item_modifiers WHERE modifier_menu_item_id = ?
               AND company_id = ? LIMIT 1''',
            (menu_item_id, company_id),
        ).fetchone():
            raise ValueError('This menu item is used as a modifier and cannot be deleted.')
        _write_menu_audit(
            conn, menu_item_id, current['code'], current['name'], user_id,
            'MENU ITEM DELETED', _menu_item_snapshot(current), None,
        )
        conn.execute(
            'DELETE FROM menu_items WHERE id = ? AND company_id = ?',
            (menu_item_id, company_id),
        )
        conn.commit()
    finally:
        conn.close()


def parse_menu_item_csv(text):
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError('CSV file is empty or missing headers.')
    required = {'Code', 'Name', 'Type', 'Category', 'Selling Price'}
    fields = {str(field or '').strip() for field in reader.fieldnames}
    if not required.issubset(fields):
        missing = ', '.join(sorted(required - fields))
        raise ValueError(f'CSV must include these columns: {missing}.')
    rows = []
    for row in reader:
        if row and any((value or '').strip() for key, value in row.items() if key is not None):
            rows.append({
                (key or '').strip(): (value or '').strip()
                for key, value in row.items() if key is not None
            })
    if not rows:
        raise ValueError('CSV file does not contain any menu items.')
    return rows


def _validate_menu_item_import_rows(rows, conn):
    categories = {
        row['name'].casefold(): row['id']
        for row in conn.execute(
            'SELECT id, name FROM menu_categories WHERE company_id = ? AND active = 1',
            (_tenant_id(),),
        ).fetchall()
    }
    existing_codes = {
        row['code'].casefold()
        for row in conn.execute(
            'SELECT code FROM menu_items WHERE company_id = ?', (_tenant_id(),)
        ).fetchall()
    }
    seen_codes = set()
    valid_rows = []
    errors = []
    for row_number, row in enumerate(rows, start=2):
        code = (row.get('Code') or '').strip()
        name = (row.get('Name') or '').strip()
        type_label = (row.get('Type') or '').strip()
        category_name = (row.get('Category') or '').strip()
        selling_price = (row.get('Selling Price') or '').strip()
        active_value = (row.get('Active') or '').strip().casefold()
        row_errors = []
        if not code:
            row_errors.append('menu item code is required')
        elif code.casefold() in seen_codes or code.casefold() in existing_codes:
            row_errors.append(f'duplicate menu item code {code}')
        if code:
            seen_codes.add(code.casefold())
        if not name:
            row_errors.append('menu item name is required')
        item_type = _normalize_menu_item_type(type_label)
        if item_type not in MENU_ITEM_TYPES:
            row_errors.append(
                'type must be Ordinary Type or Prep Screen Item'
            )
        category_id = categories.get(category_name.casefold())
        if not category_name:
            row_errors.append('category is required')
        elif category_id is None:
            row_errors.append(f'category {category_name!r} does not exist or is inactive')
        try:
            price = Decimal(selling_price)
            if not price.is_finite() or price < 0:
                raise InvalidOperation
            price = q2(price)
        except (InvalidOperation, ValueError):
            row_errors.append('selling price must be a non-negative amount')
            price = Decimal('0')
        active_values = {
            '': True, 'yes': True, 'true': True, '1': True, 'active': True,
            'no': False, 'false': False, '0': False, 'inactive': False,
        }
        if active_value not in active_values:
            row_errors.append('Active must be Yes or No')
        if row_errors:
            errors.extend(f'Row {row_number}: {error}.' for error in row_errors)
            continue
        valid_rows.append({
            'code': code,
            'name': name,
            'item_type': item_type,
            'type_label': MENU_ITEM_TYPE_LABELS[item_type],
            'category': category_name,
            'category_id': category_id,
            'selling_price': str(price),
            'active': active_values[active_value],
        })
    return valid_rows, errors


def validate_menu_item_import_rows(rows):
    conn = get_db_connection()
    try:
        return _validate_menu_item_import_rows(rows, conn)
    finally:
        conn.close()


def import_menu_items(rows, user_id):
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        valid_rows, errors = _validate_menu_item_import_rows(rows, conn)
        if errors:
            raise ValueError('\n'.join(errors))
        if not valid_rows:
            raise ValueError('CSV file does not contain any valid menu items.')
        now = datetime.utcnow().isoformat(timespec='seconds')
        imported_ids = []
        for row in valid_rows:
            cur = conn.execute(
                '''INSERT INTO menu_items
                   (company_id, code, name, item_type, category_id, selling_price, active,
                    date_created, date_modified, created_by, modified_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (_tenant_id(), row['code'], row['name'], row['item_type'], row['category_id'],
                 row['selling_price'], int(row['active']), now, now, user_id, user_id),
            )
            menu_item_id = cur.lastrowid
            imported_ids.append(menu_item_id)
            _write_menu_audit(
                conn, menu_item_id, row['code'], row['name'], user_id,
                'MENU ITEM IMPORTED', None,
                {
                    'code': row['code'], 'name': row['name'],
                    'item_type': row['item_type'], 'category_id': row['category_id'],
                    'selling_price': row['selling_price'], 'active': row['active'],
                },
            )
        conn.commit()
        return imported_ids
    finally:
        conn.close()


def _recipe_line_snapshot(row):
    return {
        'item_type': row['item_type'],
        'stock_item_id': row['stock_item_id'],
        'item_code': row['item_code'],
        'item_name': row['item_name'],
        'quantity': row['quantity'],
        'unit_cost': row['unit_cost'],
        'total_cost': row['total_cost'],
    }


def save_menu_recipe_line(menu_item_id, item_type, stock_item_id, quantity,
                          user_id, line_id=None):
    if item_type not in RECIPE_ITEM_TYPES:
        raise ValueError('Select a valid recipe item type.')
    try:
        qty = Decimal(str(quantity))
    except (InvalidOperation, ValueError):
        raise ValueError('Recipe quantity must be numeric.')
    if not qty.is_finite() or qty <= 0:
        raise ValueError('Recipe quantity must be greater than zero.')
    conn = get_db_connection()
    try:
        company_id = _tenant_id()
        menu_item = conn.execute(
            'SELECT code, name FROM menu_items WHERE id = ? AND company_id = ?',
            (menu_item_id, company_id),
        ).fetchone()
        if not menu_item:
            raise ValueError('Menu item not found.')
        stock_item = conn.execute(
            'SELECT * FROM stock_items WHERE id = ? AND company_id = ?',
            (stock_item_id, company_id),
        ).fetchone()
        if not stock_item:
            raise ValueError('Select an existing inventory item.')
        if stock_item['item_type'] != RECIPE_ITEM_TYPES[item_type]:
            raise ValueError(f'{item_type} must link to a matching inventory item type.')
        old_value = None
        action = 'RECIPE LINE CREATED'
        if line_id is not None:
            current = conn.execute(
                '''SELECT rl.*, si.code AS item_code, si.name AS item_name
                   FROM menu_item_recipe_lines rl
                   JOIN stock_items si ON si.id = rl.stock_item_id AND si.company_id = ?
                   JOIN menu_items mi ON mi.id = rl.menu_item_id AND mi.company_id = ?
                   WHERE rl.id = ? AND rl.menu_item_id = ?''',
                (company_id, company_id, line_id, menu_item_id),
            ).fetchone()
            if not current:
                raise ValueError('Recipe line not found.')
            if not stock_item['active'] and current['stock_item_id'] != stock_item['id']:
                raise ValueError('Inactive inventory items cannot be added to a recipe.')
            old_value = _recipe_line_snapshot(current)
            action = 'RECIPE LINE UPDATED'
        elif not stock_item['active']:
            raise ValueError('Inactive inventory items cannot be added to a recipe.')
        unit_cost = Decimal(str(stock_item['unit_cost']))
        total_cost = q2(qty * unit_cost)
        now_value = {
            'item_type': item_type, 'stock_item_id': stock_item_id,
            'item_code': stock_item['code'], 'item_name': stock_item['name'],
            'quantity': str(qty), 'unit_cost': str(unit_cost),
            'total_cost': str(total_cost),
        }
        if line_id is None:
            line_id = conn.execute(
                '''INSERT INTO menu_item_recipe_lines
                   (company_id, menu_item_id, item_type, stock_item_id, quantity, unit_cost, total_cost)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (company_id, menu_item_id, item_type, stock_item_id, str(qty), str(unit_cost), str(total_cost)),
            ).lastrowid
        else:
            conn.execute(
                '''UPDATE menu_item_recipe_lines
                   SET item_type = ?, stock_item_id = ?, quantity = ?, unit_cost = ?, total_cost = ?
                   WHERE id = ? AND company_id = ? AND menu_item_id = ?''',
                (item_type, stock_item_id, str(qty), str(unit_cost), str(total_cost),
                 line_id, company_id, menu_item_id),
            )
        _write_menu_audit(
            conn, menu_item_id, menu_item['code'], menu_item['name'], user_id,
            action, old_value, now_value,
        )
        conn.commit()
        return line_id
    finally:
        conn.close()


def delete_menu_recipe_line(menu_item_id, line_id, user_id):
    conn = get_db_connection()
    try:
        company_id = _tenant_id()
        menu_item = conn.execute(
            'SELECT code, name FROM menu_items WHERE id = ? AND company_id = ?',
            (menu_item_id, company_id),
        ).fetchone()
        if not menu_item:
            raise ValueError('Menu item not found.')
        current = conn.execute(
            '''SELECT rl.*, si.code AS item_code, si.name AS item_name
               FROM menu_item_recipe_lines rl
               JOIN stock_items si ON si.id = rl.stock_item_id AND si.company_id = ?
               JOIN menu_items mi ON mi.id = rl.menu_item_id AND mi.company_id = ?
               WHERE rl.id = ? AND rl.menu_item_id = ?''',
            (company_id, company_id, line_id, menu_item_id),
        ).fetchone()
        if not current:
            raise ValueError('Recipe line not found.')
        old_value = _recipe_line_snapshot(current)
        conn.execute(
            '''DELETE FROM menu_item_recipe_lines WHERE id = ? AND company_id = ?
               AND menu_item_id = ?''',
            (line_id, company_id, menu_item_id),
        )
        _write_menu_audit(
            conn, menu_item_id, menu_item['code'], menu_item['name'], user_id,
            'RECIPE LINE DELETED', old_value, None,
        )
        conn.commit()
    finally:
        conn.close()


def menu_item_audit_entries(menu_item_id):
    conn = get_db_connection()
    try:
        company_id = _tenant_id()
        return conn.execute(
            '''SELECT ma.*, u.display_name AS user_name
               FROM menu_item_audit ma
               LEFT JOIN users u ON u.id = ma.user_id
               WHERE ma.menu_item_id = ? AND ma.company_id = ?
               ORDER BY ma.created_at DESC, ma.id DESC''',
            (menu_item_id, company_id),
        ).fetchall()
    finally:
        conn.close()


def process_menu_item_sale(menu_item_id, quantity, user_id, external_reference=None):
    try:
        sold_quantity = Decimal(str(quantity))
    except (InvalidOperation, ValueError):
        raise ValueError('Sale quantity must be numeric.')
    if not sold_quantity.is_finite() or sold_quantity <= 0:
        raise ValueError('Sale quantity must be greater than zero.')
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        menu_item = conn.execute(
            'SELECT * FROM menu_items WHERE id = ? AND company_id = ? AND active = 1',
            (menu_item_id, _tenant_id()),
        ).fetchone()
        if not menu_item:
            raise ValueError('Menu item does not exist or is inactive.')
        recipe = conn.execute(
            '''SELECT rl.*, si.code AS item_code, si.name AS item_name,
                      si.quantity AS available_quantity, si.active AS item_active,
                      si.unit_cost AS current_unit_cost
               FROM menu_item_recipe_lines rl
               JOIN stock_items si ON si.id = rl.stock_item_id AND si.company_id = ?
               WHERE rl.menu_item_id = ? ORDER BY rl.id''',
            (_tenant_id(), menu_item_id),
        ).fetchall()
        if not recipe:
            raise ValueError('A recipe is required before this menu item can be sold.')
        deductions = []
        allow_negative = setting_bool('allow_negative_stock', get_setting('allow_negative_stock'))
        required_by_item = {}
        for line in recipe:
            quantity_used = Decimal(str(line['quantity'])) * sold_quantity
            if not line['item_active']:
                raise ValueError(f'Inventory item {line["item_name"]} is inactive.')
            required_by_item[line['stock_item_id']] = (
                required_by_item.get(line['stock_item_id'], Decimal('0')) + quantity_used
            )
            deductions.append((line, quantity_used))
        for line in recipe:
            if not allow_negative and Decimal(str(line['available_quantity'])) < required_by_item[line['stock_item_id']]:
                raise ValueError(
                    f'Insufficient stock for {line["item_name"]}. '
                    f'Available: {line["available_quantity"]}.'
                )
        now = datetime.utcnow().isoformat(timespec='seconds')
        transaction_id = conn.execute(
            '''INSERT INTO menu_item_inventory_transactions
               (company_id, menu_item_id, transaction_type, quantity, external_reference, user_id, created_at)
               VALUES (?, ?, 'sale', ?, ?, ?, ?)''',
            (_tenant_id(), menu_item_id, str(sold_quantity), external_reference, user_id, now),
        ).lastrowid
        for line, quantity_used in deductions:
            unit_cost = Decimal(str(line['current_unit_cost']))
            total_cost = q2(quantity_used * unit_cost)
            conn.execute(
                '''INSERT INTO menu_item_inventory_lines
                   (company_id, transaction_id, stock_item_id, item_code, item_name, quantity, unit_cost, total_cost)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (_tenant_id(), transaction_id, line['stock_item_id'], line['item_code'], line['item_name'],
                 str(quantity_used), str(unit_cost), str(total_cost)),
            )
            conn.execute(
                '''UPDATE stock_items SET quantity = CAST(quantity AS NUMERIC) - ?
                   WHERE id = ? AND company_id = ?''',
                (str(quantity_used), line['stock_item_id'], _tenant_id()),
            )
            conn.execute(
                '''INSERT INTO stock_movements
                   (company_id, item_id, movement_type, quantity, related_transaction, notes, created_at, user_id)
                   VALUES (?, ?, 'menu_sale', ?, ?, ?, ?, ?)''',
                (_tenant_id(), line['stock_item_id'], str(-quantity_used), f'MENU-TX-{transaction_id}',
                 f'Sale of {menu_item["code"]}', now, user_id),
            )
        conn.execute(
            '''INSERT INTO audit_log
               (company_id, company_name, user_id, action, module, record_id, description, created_at)
               VALUES (?, (SELECT company_name FROM companies WHERE id = ?), ?, 'MENU ITEM SOLD', 'Menu Items', ?, ?, ?)''',
            (_tenant_id(), _tenant_id(), user_id, str(transaction_id),
             f'Sold {menu_item["code"]} x {sold_quantity}; inventory deducted.', now),
        )
        conn.commit()
        return transaction_id
    finally:
        conn.close()


def process_menu_item_refund(sale_transaction_id, quantity, user_id,
                             external_reference=None):
    try:
        refund_quantity = Decimal(str(quantity))
    except (InvalidOperation, ValueError):
        raise ValueError('Refund quantity must be numeric.')
    if not refund_quantity.is_finite() or refund_quantity <= 0:
        raise ValueError('Refund quantity must be greater than zero.')
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        sale = conn.execute(
            '''SELECT mt.*, mi.code AS menu_code, mi.name AS menu_name
               FROM menu_item_inventory_transactions mt
               LEFT JOIN menu_items mi ON mi.id = mt.menu_item_id AND mi.company_id = mt.company_id
               WHERE mt.id = ? AND mt.company_id = ? AND mt.transaction_type = 'sale' ''',
            (sale_transaction_id, _tenant_id()),
        ).fetchone()
        if not sale:
            raise ValueError('Original menu item sale was not found.')
        sold_quantity = Decimal(str(sale['quantity']))
        already_refunded = sum(
            (Decimal(str(row['quantity'])) for row in conn.execute(
                '''SELECT quantity FROM menu_item_inventory_transactions
                   WHERE original_transaction_id = ? AND company_id = ?
                     AND transaction_type = 'refund' ''',
                (sale_transaction_id, _tenant_id()),
            ).fetchall()),
            Decimal('0'),
        )
        if already_refunded + refund_quantity > sold_quantity:
            raise ValueError('Refund quantity exceeds the unrefunded sale quantity.')
        sold_lines = conn.execute(
            '''SELECT * FROM menu_item_inventory_lines
               WHERE transaction_id = ? AND company_id = ? ORDER BY id''',
            (sale_transaction_id, _tenant_id()),
        ).fetchall()
        now = datetime.utcnow().isoformat(timespec='seconds')
        transaction_id = conn.execute(
            '''INSERT INTO menu_item_inventory_transactions
               (company_id, menu_item_id, transaction_type, quantity, external_reference,
                original_transaction_id, user_id, created_at)
               VALUES (?, ?, 'refund', ?, ?, ?, ?, ?)''',
            (_tenant_id(), sale['menu_item_id'], str(refund_quantity), external_reference,
             sale_transaction_id, user_id, now),
        ).lastrowid
        for line in sold_lines:
            returned_quantity = (
                Decimal(str(line['quantity'])) / sold_quantity * refund_quantity
            )
            total_cost = q2(returned_quantity * Decimal(str(line['unit_cost'])))
            conn.execute(
                '''INSERT INTO menu_item_inventory_lines
                   (company_id, transaction_id, stock_item_id, item_code, item_name, quantity, unit_cost, total_cost)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (_tenant_id(), transaction_id, line['stock_item_id'], line['item_code'], line['item_name'],
                 str(returned_quantity), line['unit_cost'], str(total_cost)),
            )
            if line['stock_item_id'] is not None:
                conn.execute(
                    '''UPDATE stock_items SET quantity = CAST(quantity AS NUMERIC) + ?
                       WHERE id = ? AND company_id = ?''',
                    (str(returned_quantity), line['stock_item_id'], _tenant_id()),
                )
                conn.execute(
                    '''INSERT INTO stock_movements
                       (company_id, item_id, movement_type, quantity, related_transaction, notes, created_at, user_id)
                       VALUES (?, ?, 'menu_refund', ?, ?, ?, ?, ?)''',
                    (_tenant_id(), line['stock_item_id'], str(returned_quantity), f'MENU-TX-{transaction_id}',
                     f'Refund of {sale["menu_code"] or "deleted menu item"}', now, user_id),
                )
        conn.execute(
            '''INSERT INTO audit_log
               (company_id, company_name, user_id, action, module, record_id, description, created_at)
               VALUES (?, (SELECT company_name FROM companies WHERE id = ?), ?, 'MENU ITEM REFUNDED', 'Menu Items', ?, ?, ?)''',
            (_tenant_id(), _tenant_id(), user_id, str(transaction_id),
             f'Refunded {sale["menu_code"] or "deleted menu item"} x {refund_quantity}; inventory returned.', now),
        )
        conn.commit()
        return transaction_id
    finally:
        conn.close()


def list_stock_items():
    conn = get_db_connection()
    try:
        company_id = _tenant_id()
        rows = conn.execute(
            '''SELECT si.*, c.name AS category_name FROM stock_items si
               LEFT JOIN categories c ON c.id = si.category_id AND c.company_id = si.company_id
               WHERE si.company_id = ? ORDER BY si.name''',
            (company_id,),
        ).fetchall()
    finally:
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
    params = [_tenant_id()]
    clauses.append('si.company_id = ?')
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
                   LEFT JOIN categories c ON c.id = si.category_id AND c.company_id = si.company_id
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
    try:
        return conn.execute(
            'SELECT * FROM stock_items WHERE id = ? AND company_id = ?',
            (item_id, _tenant_id()),
        ).fetchone()
    finally:
        conn.close()


def set_stock_item_active(item_id, active, modified_by):
    if active not in (0, 1):
        raise ValueError('Stock item status must be active or inactive.')
    conn = get_db_connection()
    try:
        company_id = _tenant_id()
        current = conn.execute(
            'SELECT code, notes FROM stock_items WHERE id = ? AND company_id = ?',
            (item_id, company_id),
        ).fetchone()
        if not current:
            raise ValueError('Stock item not found.')
        if active == 0 and not (current['notes'] or '').strip():
            raise ValueError('Add a note in the stock item edit screen before marking it inactive.')
        now = datetime.utcnow().isoformat(timespec='seconds')
        conn.execute(
            '''UPDATE stock_items SET active = ?, date_modified = ?, modified_by = ?
               WHERE id = ? AND company_id = ?''',
            (active, now, modified_by, item_id, company_id),
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
        company_id = _tenant_id()
        if conn.execute(
            'SELECT 1 FROM stock_items WHERE company_id = ? AND lower(code) = lower(?)',
            (company_id, code.strip()),
        ).fetchone():
            raise ValueError('Stock code already exists.')
        if not conn.execute(
            'SELECT 1 FROM categories WHERE id = ? AND company_id = ? AND active = 1',
            (category_id, company_id),
        ).fetchone():
            raise ValueError('Select an active stock category.')
        now = datetime.utcnow().isoformat(timespec='seconds')
        cur = conn.execute(
            '''INSERT INTO stock_items
               (company_id, code, name, item_type, unit, quantity, category_id, active,
                date_created, date_modified, created_by, modified_by, unit_cost)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)''',
            (company_id, code.strip(), name.strip(), item_type, unit, str(qty), category_id,
             now, now, created_by, created_by, str(cost))
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
        company_id = _tenant_id()
        current = conn.execute(
            'SELECT * FROM stock_items WHERE id = ? AND company_id = ?',
            (item_id, company_id),
        ).fetchone()
        if not current:
            raise ValueError('Stock item not found.')
        if current['code'].lower() != code.strip().lower():
            existing = conn.execute(
                '''SELECT 1 FROM stock_items WHERE company_id = ?
                   AND lower(code) = lower(?) AND id != ?''',
                (company_id, code.strip(), item_id),
            ).fetchone()
            if existing:
                raise ValueError('Another stock item already uses this code.')
        if not conn.execute(
            'SELECT 1 FROM categories WHERE id = ? AND company_id = ?',
            (category_id, company_id),
        ).fetchone():
            raise ValueError('Select a stock category belonging to this company.')
        now = datetime.utcnow().isoformat(timespec='seconds')
        conn.execute(
            '''UPDATE stock_items SET code = ?, name = ?, item_type = ?, unit = ?,
               quantity = ?, category_id = ?, active = ?, date_modified = ?, modified_by = ?,
               unit_cost = ?, notes = ? WHERE id = ? AND company_id = ?''',
            (code.strip(), name.strip(), item_type, unit, str(qty), category_id,
             1 if active else 0, now, modified_by, str(cost), notes.strip(), item_id, company_id)
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
        company_id = _tenant_id()
        accepted = []
        rejected = []
        now = datetime.utcnow().isoformat(timespec='seconds')
        for row in rows:
            category = conn.execute(
                '''SELECT id FROM categories WHERE company_id = ? AND lower(name) = lower(?)
                   AND active = 1''',
                (company_id, row['category']),
            ).fetchone()
            if not category:
                rejected.append({**row, 'error': 'Category does not exist or is inactive'})
                continue
            if conn.execute(
                'SELECT 1 FROM stock_items WHERE company_id = ? AND lower(code) = lower(?)',
                (company_id, row['code']),
            ).fetchone():
                rejected.append({**row, 'error': 'Duplicate stock code found'})
                continue
            cur = conn.execute(
                '''INSERT INTO stock_items
                   (company_id, code, name, unit, quantity, category_id, active,
                    date_created, date_modified, created_by, modified_by, unit_cost)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)''',
                (company_id, row['code'], row['name'], row['unit'], row['quantity'],
                 category['id'], now, now, user_id, user_id, '0.00')
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
        company_id = _tenant_id()
        output = conn.execute(
            'SELECT * FROM stock_items WHERE id = ? AND company_id = ?',
            (output_item_id, company_id),
        ).fetchone()
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
            item = conn.execute(
                'SELECT * FROM stock_items WHERE id = ? AND company_id = ?',
                (item_id, company_id),
            ).fetchone()
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
            '''INSERT INTO manufacturing_transactions
               (company_id, output_item_id, expected_output, actual_output, total_input_quantity,
                yield_percentage, manufacturing_date, user_id, notes, total_cost, cost_per_unit)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (company_id, output_item_id, str(expected), str(actual), str(total_input),
             str(yield_pct), now, user_id, notes, str(q2(total_cost)), str(q2(cost_per_unit)))
        )
        transaction_id = cur.lastrowid
        for item, q, ingredient_cost in ingredient_entries:
            conn.execute(
                '''INSERT INTO manufacturing_ingredients
                   (company_id, transaction_id, item_id, quantity, unit_cost, total_cost)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (company_id, transaction_id, item['id'], str(q), str(item['unit_cost']), str(q2(ingredient_cost))),
            )
            if not bypass_stock_update:
                conn.execute(
                    '''UPDATE stock_items SET quantity = quantity - ?, date_modified = ?
                       WHERE id = ? AND company_id = ?''',
                    (str(q), now, item['id'], company_id),
                )
        if not bypass_stock_update:
            conn.execute(
                '''UPDATE stock_items SET quantity = quantity + ?, date_modified = ?
                   WHERE id = ? AND company_id = ?''',
                (str(actual), now, output_item_id, company_id),
            )
            if setting_bool('manufacturing_auto_cost', get_setting('manufacturing_auto_cost')):
                conn.execute(
                    'UPDATE stock_items SET unit_cost = ? WHERE id = ? AND company_id = ?',
                    (str(q2(cost_per_unit)), output_item_id, company_id),
                )
            conn.execute(
                '''INSERT INTO stock_movements
                   (company_id, item_id, movement_type, quantity, related_transaction,
                    notes, created_at, user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (company_id, output_item_id, 'manufacturing_output', str(actual),
                 f'MFG-{transaction_id}', notes, now, user_id),
            )
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
        company_id = _tenant_id()
        calculator_mode = setting_bool('calculator_mode', get_setting('calculator_mode'))
        source = conn.execute(
            'SELECT * FROM stock_items WHERE id = ? AND company_id = ?',
            (source_item_id, company_id),
        ).fetchone()
        dest = conn.execute(
            'SELECT * FROM stock_items WHERE id = ? AND company_id = ?',
            (destination_item_id, company_id),
        ).fetchone()
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
        session_id = conn.execute(
            '''INSERT INTO portioning_sessions(company_id, source_item_id, session_date, user_id, notes)
               VALUES (?, ?, ?, ?, ?)''',
            (company_id, source_item_id, now, user_id, notes),
        ).lastrowid
        conn.execute(
            '''INSERT INTO portioning_transactions
               (company_id, session_id, source_item_id, destination_item_id, original_quantity,
                quantity_portioned, waste_quantity, yield_percentage, original_cost, adjusted_cost,
                transaction_date, user_id, notes, transaction_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (company_id, session_id, source_item_id, destination_item_id, source['quantity'],
             str(qty), '0.00', '100.00', '0.00', '0.00', now, user_id,
             transaction_notes, 'bulk')
        )
        if not calculator_mode:
            conn.execute(
                'UPDATE stock_items SET quantity = quantity - ? WHERE id = ? AND company_id = ?',
                (str(qty), source_item_id, company_id),
            )
            conn.execute(
                'UPDATE stock_items SET quantity = quantity + ? WHERE id = ? AND company_id = ?',
                (str(qty), destination_item_id, company_id),
            )
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
        company_id = _tenant_id()
        calculator_mode = setting_bool('calculator_mode', get_setting('calculator_mode'))
        source = conn.execute(
            'SELECT * FROM stock_items WHERE id = ? AND company_id = ?',
            (source_item_id, company_id),
        ).fetchone()
        if not source:
            raise ValueError('Source stock item does not exist.')
        if destination_item_id:
            dest = conn.execute(
                'SELECT * FROM stock_items WHERE id = ? AND company_id = ?',
                (destination_item_id, company_id),
            ).fetchone()
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
        session_id = conn.execute(
            '''INSERT INTO portioning_sessions(company_id, source_item_id, session_date, user_id, notes)
               VALUES (?, ?, ?, ?, ?)''',
            (company_id, source_item_id, now, user_id, notes),
        ).lastrowid
        conn.execute(
            '''INSERT INTO portioning_transactions
               (company_id, session_id, source_item_id, destination_item_id, original_quantity,
                quantity_portioned, waste_quantity, yield_percentage, original_cost, adjusted_cost,
                transaction_date, user_id, notes, transaction_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (company_id, session_id, source_item_id, destination_item_id or source_item_id,
             str(original), str(usable), str(result['waste_quantity']),
             str(result['yield_percentage']), str(cost), str(result['adjusted_cost_per_unit']),
             now, user_id, transaction_notes, 'yield_loss')
        )
        if not calculator_mode:
            conn.execute(
                'UPDATE stock_items SET quantity = quantity - ? WHERE id = ? AND company_id = ?',
                (str(original), source_item_id, company_id),
            )
            if destination_item_id:
                conn.execute(
                    'UPDATE stock_items SET quantity = quantity + ? WHERE id = ? AND company_id = ?',
                    (str(usable), destination_item_id, company_id),
                )
        conn.commit()
        return {'session_id': session_id, 'adjusted_cost_per_unit': result['adjusted_cost_per_unit'], 'yield_warning': result['yield_warning']}
    finally:
        conn.close()


def list_recent_portioning(limit=10):
    conn = get_db_connection()
    try:
        company_id = _tenant_id()
        return conn.execute(
            '''SELECT pt.*, s.name AS source_name, d.name AS destination_name,
                      u.display_name AS user_name
               FROM portioning_transactions pt
               LEFT JOIN stock_items s ON s.id = pt.source_item_id AND s.company_id = pt.company_id
               LEFT JOIN stock_items d ON d.id = pt.destination_item_id AND d.company_id = pt.company_id
               LEFT JOIN users u ON u.id = pt.user_id AND u.company_id = pt.company_id
               WHERE pt.company_id = ? ORDER BY pt.transaction_date DESC LIMIT ?''',
            (company_id, limit),
        ).fetchall()
    finally:
        conn.close()


def dashboard_metrics():
    conn = get_db_connection()
    company_id = _tenant_id()
    metrics = {
        'total_stock_items': conn.execute('SELECT COUNT(*) FROM stock_items WHERE company_id = ?', (company_id,)).fetchone()[0],
        'manufacturing_transactions': conn.execute('SELECT COUNT(*) FROM manufacturing_transactions WHERE company_id = ?', (company_id,)).fetchone()[0],
        'portioning_transactions': conn.execute('SELECT COUNT(*) FROM portioning_transactions WHERE company_id = ?', (company_id,)).fetchone()[0],
        'recent_activity': conn.execute('SELECT COUNT(*) FROM audit_log WHERE company_id = ?', (company_id,)).fetchone()[0],
    }
    conn.close()
    return metrics


def audit_entries(limit=20):
    conn = get_db_connection()
    retention = setting_int('audit_retention_days', get_setting('audit_retention_days'))
    query = '''SELECT al.*, u.display_name AS user_name FROM audit_log al
               LEFT JOIN users u ON u.id = al.user_id'''
    params = [_tenant_id()]
    query += ' WHERE al.company_id = ?'
    if retention > 0:
        query += " AND al.created_at >= datetime('now', ?)"
        params.append(f'-{retention} days')
    query += ' ORDER BY al.created_at DESC LIMIT ?'
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return rows


def list_manufacturing_history(limit=20):
    conn = get_db_connection()
    rows = conn.execute(
        '''SELECT mt.*, o.name AS output_name, u.display_name AS user_name
           FROM manufacturing_transactions mt
           LEFT JOIN stock_items o ON o.id = mt.output_item_id AND o.company_id = mt.company_id
           LEFT JOIN users u ON u.id = mt.user_id AND u.company_id = mt.company_id
           WHERE mt.company_id = ? ORDER BY mt.manufacturing_date DESC LIMIT ?''',
        (_tenant_id(), limit)
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
    company_id = _tenant_id()
    conn.execute(
        '''INSERT INTO audit_log
           (company_id, company_name, user_id, action, module, record_id, description, created_at)
           VALUES (?, (SELECT company_name FROM companies WHERE id = ?), ?, ?, ?, ?, ?, ?)''',
        (company_id, company_id, user_id, action, module, str(record_id), description, now)
    )
    conn.commit()
    conn.close()
