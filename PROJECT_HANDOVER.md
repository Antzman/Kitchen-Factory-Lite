# Kitchen Factory - Project Handover

## Document purpose

This document describes the current Kitchen Factory application for a senior
developer or software architect taking over the project. Business behavior is
described first, followed by the technical implementation, current progress,
known limitations, and operating instructions.

## 1. Business Purpose

Kitchen Factory is a hospitality kitchen application for stock control,
manufacturing, portioning, yield management, food costing, and operational
review. It uses one shared stock-item database for raw materials, manufactured
items, and portioned items.

The application is an operational kitchen tool, not a full ERP or accounting
system. It supports:

- Stock-item master data and stock balances.
- Cost per kilogram or litre and inventory value.
- Manufacturing recipes and stock consumption.
- Bulk portioning and yield-loss recording.
- Waste, yield, costing, notes, and audit history.
- A stock-count and costing report.
- Configurable operating behavior and appearance.

## 2. Core Concepts

### Business explanation

- **Stock Item**: A uniquely coded item, such as `MILK-001 - Milk`.
- **Stock Item Type**: Raw Material, Manufactured Item, or Portioned Item.
- **Quantity**: The current stock balance.
- **Unit**: `kg`, `L`, or `each`. Use `each` for countable items such as
  individual portions, packs, or pieces.
- **Cost per Unit**: The current cost for one kilogram or litre.
- **Total Cost**: Quantity multiplied by cost per unit.
- **Manufacturing**: Consumes ingredient stock and increases an existing output
  stock item.
- **Portioning**: Transfers stock or records usable quantity after preparation
  loss.
- **Calculator Mode**: Saves manufacturing and portioning history without
  changing stock balances.
- **Audit Entry**: A user, timestamp, action, module, and description record.
- **Inactive Item**: A stock item retained for history but marked in red and
  requiring a saved explanatory note before deactivation.

### Technical explanation

The application is a Flask web application backed by SQLite. Routes in
`app.py` handle requests and delegate validation, calculations, and database
updates to `services.py`. Templates use Jinja2. Quantities and costs use
Python `Decimal`; currency values are normally quantized with
`ROUND_HALF_UP`.

## 3. Current Navigation and User Workflow

The authenticated sidebar currently contains:

- **My Dashboard** - dashboard metrics, recent activity, and stock snapshot.
- **Stock Item Database** - stock CRUD, status changes, and CSV import.
- **Manufacturing System** - shared-stock manufacturing transactions.
- **Portioning System** - separate Bulk Portioning and Yield Loss tabs.
- **Reports** - central reporting hub.
- **Settings** - operational settings, user management, and category management.
- **About** - application information.
- **Logout**.

The About page is `/about` and displays version 1.0.0, technology choices,
application purpose, and author information. Authentication currently protects
it like other non-login application routes.

## 4. Login and User Management

Login is username-only:

1. A user enters a username.
2. The application checks that the user exists and is active.
3. The username is stored in the Flask session.
4. Authenticated routes become available.

There are no passwords, MFA, password resets, or external identity providers.
Users can be added, edited, activated, and deactivated from `/users`, which is
linked from the Settings page. Physical deletion is intentionally avoided so
historical records remain attributable. Roles are stored as text but are not
currently enforced for authorization.

Seeded users on an empty database are:

- `admin` - System Admin - Administrator
- `manager` - Kitchen Manager - Manager
- `user` - Kitchen User - User

## 5. Stock Item Logic

### Business rules

- Codes are required and unique case-insensitively.
- Names and units are required.
- Units are limited to `kg`, `L`, and `each`.
- New or edited stock quantities cannot be negative.
- Cost per unit cannot be negative.
- Categories are selected from active categories.
- Item type must be raw material, manufactured item, or portioned item.
- An item cannot be made inactive until a non-empty note has been saved.
- Inactive rows are rendered red.
- The inventory table sorts Code, Name, Unit, Category, Item Type, and cost
  fields where supported by the current table controls; quantity behavior
  remains governed by the current template implementation.

### Cost calculation

```text
total cost = quantity × cost per unit
```

The server calculates total cost in `list_stock_items()` and the stock item
report query. The edit form provides a live browser preview, but server-side
validation remains authoritative.

### Categories

Categories can be created, edited, activated, and deactivated from
`/categories`. Inactive categories are not offered for new stock-item
selection.

## 6. Manufacturing Logic

The manufacturing system uses the same `stock_items` table for both output and
ingredients. No separate manufacturing inventory exists.

Workflow:

1. Select an existing stock item whose type is **Manufactured Item**.
2. Select one or more existing ingredient stock items.
3. Enter ingredient quantities.
4. Review live total input quantity, ingredient cost, output quantity, and
   manufactured cost per unit.
5. Enter notes when required by settings.
6. Confirm when required by settings.
7. Process the transaction.

Manufacturing output selection is restricted to Manufactured Item stock types,
and the service layer enforces the same rule for direct requests. Ingredient
selection continues to use the shared stock-item database and is not narrowed
by type.

Calculations:

```text
ingredient cost = ingredient quantity × current ingredient unit cost
total manufacturing cost = sum of ingredient costs
manufactured cost per unit = total manufacturing cost ÷ output quantity
```

Processing stores a transaction header and ingredient detail rows with
quantity, unit-cost snapshots, and total-cost snapshots. Normal processing
decreases ingredient quantities and increases the output quantity. When
automatic output costing is enabled, the output item's cost per unit is
updated to the calculated manufactured cost.

The database retains `expected_output`, but the current web form primarily uses
the actual output and passes that value into both fields.

## 7. Portioning Logic

The Portioning page has two separate tabs.

### Bulk Portioning

Bulk portioning transfers a quantity from one existing stock item to another.
Source and destination must differ, must exist, and must use the same unit.
The source is reduced and the destination is increased during normal mode.
The destination selector and server-side validation only allow stock items
whose type is **Portioned Item**. Source selection remains available across the
shared stock-item database.

### Yield Loss

Yield-loss portioning records original quantity, usable quantity, original
total cost, optional destination, waste, yield percentage, and adjusted cost.
When a destination is supplied, it must be a **Portioned Item** stock type;
otherwise the usable yield remains on the source item.

Rules:

- Original and usable quantities must be greater than zero.
- Usable quantity cannot exceed original quantity.
- Original total cost cannot be negative.
- Source stock must be sufficient unless negative stock or Calculator Mode
  permits the operation.
- A configured waste reason is required when enabled.

## 8. Yield Loss Calculations

Implemented by `calculate_yield_loss()`:

```text
waste quantity = original quantity - usable quantity
yield percentage = usable quantity ÷ original quantity × 100
adjusted cost per usable unit = original total cost ÷ usable quantity
```

A configured minimum yield produces a warning; it does not currently block the
transaction.

## 9. Settings Architecture

Settings are defined in `settings.py`, persisted in the `system_settings`
table, seeded by `db.py`, and read through `get_setting()` / `get_settings()`.
Invalid choice values fall back to their defined defaults.

### General

- Calculator Mode.
- Default report rows.
- Currency symbol.
- Company name.
- Default export format.
- Logo placeholder.
- Audit level.
- Audit retention days.
- Audit logging enabled/disabled.

### Inventory

- Allow negative stock. This applies to manufacturing and portioning.

### Manufacturing

- Require manufacturing notes.
- Require manufacturing confirmation.
- Automatically update manufactured output cost.

### Portioning

- Require waste reason.
- Minimum yield warning percentage.

### Appearance

- Appearance mode: Light Mode or Dark Mode.
- Colour scheme: Kitchen Green or Kitchen Blue.

Appearance is applied globally through CSS variables in
`static/styles.css`. Invalid appearance values default to Light Mode and
Kitchen Green. Legacy appearance keys such as `appearance_theme`,
`appearance_density`, `appearance_system_default`, `appearance_accent`, and
`appearance_font_size` are migrated/removed and are no longer active settings.

### Users

User management is accessible from Settings and uses the existing `/users`
route. It is a management link rather than a system setting.

## 10. Calculator Mode and Negative Stock

When Calculator Mode is enabled:

- Manufacturing and portioning calculations are validated and saved.
- History records are created.
- Stock balances are not changed.
- Stock movement updates are not performed.
- Availability checks are bypassed for simulation purposes.

When Calculator Mode is disabled, the normal stock-update behavior applies.

When Allow Negative Stock is enabled, manufacturing and portioning may reduce
stock below zero. This setting is separate from Calculator Mode.

## 11. Audit Trail Logic

The `audit_log` table records application-level events such as:

- Stock creation, edits, imports, and status changes.
- Category changes.
- Manufacturing transactions.
- Portioning transactions.
- Settings changes.
- Other configured operational events.

Audit behavior is controlled by:

- `audit_enabled`.
- `audit_level`: minimal, standard, or detailed.
- `audit_retention_days`, where zero means indefinite retention in the query.

The Audit Log is available through Reports as `/audit-log`. It is descriptive
logging, not immutable database-trigger auditing or a before/after field
snapshot system.

## 12. Reporting Features

`/reports` is the central reporting hub. It currently presents:

### Inventory Reports

- **Stock Item Report** - implemented at `/reports/stock-items`.
- Low Stock Report - hub placeholder, not yet implemented.
- Negative Stock Report - hub placeholder, not yet implemented.
- Inventory Value Report - hub placeholder, not yet implemented.

### Manufacturing Reports

- Manufacturing History - implemented as a report section and on the
  manufacturing page.
- Manufacturing Cost Analysis - hub placeholder.
- Ingredient Usage Report - hub placeholder.

### Portioning Reports

- Portioning History - implemented as a report section.
- Yield Loss Report - hub placeholder.
- Waste Report - hub placeholder.

### System Reports

- User Activity Report - currently linked to the audit view.
- Audit Log Report - implemented at `/audit-log`.
- Settings Change Report - currently represented through the audit view; it
  does not yet have a dedicated filtered route.

### Stock Item Report

The stock report supports:

- Search by code, name, or category.
- Filters for category, item type, unit, and status.
- Server-side sorting and pagination.
- Total stock items, active items, inactive items, and inventory value.
- CSV, XLSX, and PDF exports.
- Print layout with company name, report name, generated date, and user.
- Green active badges and red inactive badges.

The report is intended as an operational stock-count and costing reference,
not an accounting report.

The legacy `/export-csv` route remains available and exports a smaller basic
stock dataset. XLSX uses `openpyxl`; PDF uses `reportlab`.

## 13. Database Design

SQLite is stored in `kitchen_factory.db`. `init_db()` in `db.py` creates the
schema and performs lightweight migrations. Current tables are:

- `categories`
- `users`
- `stock_items`
- `manufacturing_transactions`
- `manufacturing_ingredients`
- `portioning_sessions`
- `portioning_transactions`
- `system_settings`
- `audit_log`
- `stock_movements`

Important relationships:

```text
categories 1 ──── * stock_items
users 1 ──── * manufacturing_transactions
users 1 ──── * portioning_sessions
users 1 ──── * portioning_transactions
users 1 ──── * audit_log
users 1 ──── * stock_movements
stock_items 1 ──── * manufacturing_transactions (output)
manufacturing_transactions 1 ──── * manufacturing_ingredients
stock_items 1 ──── * manufacturing_ingredients (ingredient)
portioning_sessions 1 ──── * portioning_transactions
stock_items 1 ──── * portioning_transactions (source/destination)
stock_items 1 ──── * stock_movements
```

Manufacturing output movements are recorded. Movement coverage for all stock
edits and portioning operations is still incomplete.

## 14. Folder Structure

```text
Kitchen Factory/
├── app.py
├── db.py
├── models.py
├── services.py
├── settings.py
├── requirements.txt
├── kitchen_factory.db
├── PROJECT_HANDOVER.md
├── static/
│   └── styles.css
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── about.html
│   ├── dashboard.html
│   ├── stock_items.html
│   ├── stock_item_edit.html
│   ├── import_stock.html
│   ├── manufacturing.html
│   ├── portioning.html
│   ├── reports.html
│   ├── stock_item_report.html
│   ├── settings.html
│   ├── categories.html
│   ├── users.html
│   └── audit_log.html
└── tests/
    └── test_calculations.py
```

## 15. Current Progress

Implemented:

- Flask application factory and SQLite bootstrap.
- Session-based username login.
- Shared stock-item database.
- Stock CRUD, notes, types, categories, cost per unit, and total cost.
- Active/inactive status with saved-note requirement.
- CSV stock import.
- Stock sorting and operational Stock Item Report.
- Manufacturing with live costing and snapshots.
- Negative-stock and Calculator Mode settings.
- Bulk portioning and yield-loss portioning.
- Waste reasons and minimum-yield warnings.
- Dashboard metrics and activity snapshot.
- Central Reports hub.
- Audit log and configurable audit behavior.
- Settings architecture with grouped UX and database persistence.
- Global Light/Dark appearance and Kitchen Green/Blue colour schemes.
- About page with version and technology information.
- CSV, XLSX, PDF, and print support for the Stock Item Report.

The automated suite currently contains three calculation-focused tests. Manual
route smoke tests have been used for the major application pages.

## 16. Known Issues

1. Authentication is not production-ready: no passwords, MFA, password reset,
   secure identity integration, or robust session configuration.
2. Stored roles are not enforced as route permissions.
3. Manufacturing expected output is retained in the schema but is not a
   separate current UI input.
4. Ingredient/output units must match exactly; there is no conversion policy.
5. Stock imports do not import cost per unit, notes, or item type.
6. The legacy CSV export omits cost fields.
7. Stock movement coverage is incomplete outside manufacturing output.
8. Several report hub entries are navigation placeholders, not implemented
   report routes.
9. Audit entries do not contain immutable before/after field snapshots.
10. Database migrations are lightweight and not versioned.
11. The Flask secret key is hard-coded.
12. SQLite connection handling has no pooling or explicit concurrency strategy.
13. Browser summaries are advisory; the server recalculates and validates.

## 17. Future Improvements

1. Add password-based or organization identity authentication.
2. Enforce role permissions.
3. Add versioned migrations and backup/restore procedures.
4. Separate expected and actual manufacturing output in the UI.
5. Implement the remaining report hub reports and date/user filters.
6. Complete stock movement coverage.
7. Add cost, notes, and item type to import/export.
8. Add manufacturing detail and transaction review pages.
9. Expand route-level tests and rollback tests.
10. Move secrets, database path, logging, and configuration to environment
    configuration.
11. Add CSRF protection, secure cookies, rate limiting, and structured errors.
12. Consider PostgreSQL if concurrent usage grows.

## 18. Technical Setup

Runtime:

- Python
- Flask 3.0.3
- SQLite
- Jinja2
- Browser JavaScript
- CSS variables and responsive CSS

Dependencies in `requirements.txt`:

```text
Flask==3.0.3
pytest==8.3.2
openpyxl==3.1.5
reportlab==4.2.5
waitress==3.0.2
pyinstaller==6.22.3
```

Entry points:

- `create_app()` in `app.py`
- Module-level `app = create_app()`
- Direct execution through `python app.py`

Important service functions include:

- `calculate_yield_loss()`
- `create_stock_item()`
- `update_stock_item()`
- `set_stock_item_active()`
- `create_manufacturing_transaction()`
- `create_bulk_portioning()`
- `create_yield_loss_portioning()`
- `list_stock_items()`
- `stock_item_report()`
- `add_audit()`
- `get_setting()` / `get_settings()` / `update_settings()`

Windows distribution files:

- `launch.py` starts Waitress and opens the browser automatically.
- `KitchenFactory.spec` defines the windowless PyInstaller executable.
- `installer/KitchenFactory.iss` creates the Windows installer and shortcuts.
- `build_windows.ps1` builds the executable and installer.
- `DEPLOYMENT_GUIDE.md` contains the release checklist and troubleshooting.

## 19. How To Run The Application

From Windows PowerShell:

```powershell
cd "C:\Users\antzm\Kitchen Factory"
python -m pip install -r requirements.txt
python app.py
```

Open:

```text
http://127.0.0.1:5000/login
```

Seeded usernames are `admin`, `manager`, and `user`; there are currently no
passwords.

For non-technical Windows distribution, build and run
`release/KitchenFactorySetup.exe`. The installed application stores its
database in `%LOCALAPPDATA%\Kitchen Factory\kitchen_factory.db`, starts a
local Waitress server, and opens the default browser at the login page.

Run tests:

```powershell
python -m pytest -q
```

On first startup the database is created and seeded with categories, users,
demo stock items, and default settings.

## 20. Important Business Rules

1. Stock items are the master records for ingredients and manufactured items.
2. Manufacturing must not create a separate inventory database.
3. Manufactured outputs and ingredients must already exist in `stock_items`.
4. Codes must be unique.
5. Units are limited to kilograms, litres, and countable each-items.
6. Inactive stock requires a saved explanatory note.
7. Manufacturing cost is the sum of ingredient quantity multiplied by
   ingredient unit cost.
8. Portioning requires compatible source and destination units.
9. Yield loss is original quantity minus usable quantity.
10. Negative stock is allowed only when configured.
11. Calculator Mode saves history but does not change stock balances.
12. Settings are persisted in `system_settings`.
13. Invalid appearance settings fall back to Light Mode and Kitchen Green.
14. Historical records should be retained when users or categories are
    deactivated rather than physically deleted.
15. Server-side validation is authoritative over browser calculations.
