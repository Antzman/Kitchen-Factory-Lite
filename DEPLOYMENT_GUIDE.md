# Kitchen Factory 1.0.0 Deployment Guide

This guide describes how to build and distribute Kitchen Factory to Windows
users who do not have Python, VS Code, or Command Prompt available.

Kitchen Factory is a hospitality kitchen calculator and operational costing
tool. It is not an ERP system and the deployment package does not add
accounting, purchasing, suppliers, payroll, general ledger, or POS features.

## Release contents

- `launch.py` starts the local Waitress web server and opens the default browser.
- `KitchenFactory.spec` defines the PyInstaller executable.
- `installer/KitchenFactory.iss` defines the Inno Setup installer.
- `build_windows.ps1` builds the executable and, when Inno Setup is installed,
  builds `release/KitchenFactorySetup.exe`.
- `templates/` and `static/` are bundled into the executable.
- The SQLite database is created at
  `%LOCALAPPDATA%\Kitchen Factory\kitchen_factory.db` for installed builds.

## Build prerequisites

Build on a Windows machine with:

1. Python 3.11 or newer.
2. Inno Setup 6, downloaded from the official Inno Setup website.
3. The Kitchen Factory source folder.

The target user's machine does not need Python or Inno Setup.

## Build steps

Open PowerShell in the project folder and run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
.\build_windows.ps1
```

The script:

1. Removes prior `build`, `dist`, and `release` output.
2. Runs PyInstaller using `KitchenFactory.spec`.
3. Compiles the Inno Setup script when `ISCC.exe` is available.

If Inno Setup is not installed, the executable is still produced at
`dist\KitchenFactory.exe`. Install Inno Setup 6 and run:

```powershell
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" installer\KitchenFactory.iss
```

The installer is created at:

```text
release\KitchenFactorySetup.exe
```

## PyInstaller command

The direct equivalent of the executable build is:

```powershell
pyinstaller --clean --noconfirm KitchenFactory.spec
```

The build uses a windowless executable, includes Flask templates and static
assets, and uses Waitress rather than Flask's development server.

## Installer behavior

`KitchenFactorySetup.exe`:

- Installs Kitchen Factory under `Program Files`.
- Creates a Desktop shortcut.
- Creates a Start Menu shortcut.
- Registers Kitchen Factory with Windows installed applications.
- Provides an uninstall entry.
- Offers to launch Kitchen Factory after installation.

The application itself runs locally at:

```text
http://127.0.0.1:5000/login
```

The browser opens automatically when the application starts. No command
prompt, Python installation, or Flask configuration is required.

## Database behavior

On first launch, the application creates
`%LOCALAPPDATA%\Kitchen Factory\kitchen_factory.db` for installed builds,
initializes the schema, and applies non-destructive migrations. There are no
shared demo accounts. Register the company and first Company Administrator at
`/register`; each company receives its own stock categories, Menu Categories
(`Food` and `Beverages`), and settings.

When an older database contains data but no company, it is assigned to a
one-time legacy workspace. The first company registration claims that workspace
so the existing records are retained and available to the new administrator.
Existing legacy user accounts are disabled; create new company users after
registration.

Installed builds store the database in the user's writable profile rather than
under `Program Files`. This avoids requiring administrator permissions for
normal stock, manufacturing, portioning, menu item, reporting, and settings
work.

Existing databases remain supported by the normal initialization and migration
logic. To move an existing database into an installed build, close Kitchen
Factory and copy the database to:

```text
%LOCALAPPDATA%\Kitchen Factory\kitchen_factory.db
```

The application continues to support `python app.py` and local access at
`http://127.0.0.1:5000`. It uses SQLite without requiring Render or another
cloud service. For an HTTPS deployment, set `KITCHEN_FACTORY_COOKIE_SECURE=1`;
local HTTP testing leaves this disabled so the browser can send its session
cookie.

## Temporary beta/demo mode

The application currently starts with `DEMO_MODE = True` in `app.py`. In this
mode, visitors are automatically signed in to the shared Kitchen Factory Demo
company; login, registration, authentication checks, and CSRF validation are
bypassed. The banner **“DEMO MODE - Data may be reset at any time.”** is shown
throughout the application. All demo visitors can view and change the same demo
company data.
On the first startup with an empty demo inventory, the application imports the
permanent sample stock list from `demo_stock_data.py`. The seed runs only when
the demo company's stock database is empty; later edits are retained and no
additional seed copies are added.

To restore normal login and security checks, set `DEMO_MODE = False` in
`app.py` and restart the application. Do not expose the demo deployment as a
private or production environment.

Company users should create passwords of at least 12 characters. The application currently disables email verification and user-facing
password-reset-by-email flows. To recover access, users should contact the
support address shown in the login page and footer: `pumbaskitchenapp@gmail.com`.

Company registrations create active accounts immediately and sign the
registrant in. An administrator can generate a temporary password for any
user from the Users management screen; the temporary password must be
changed by the user at first login. All administrator-generated password
resets are recorded in the audit log.

The database retains the verification- and reset-related fields (verification
tokens, expiry, and delivery log) so the email workflows can be re-enabled
later if desired. To restore email delivery, reintroduce an email provider
implementation and update the deployment environment with the provider's API
key or SMTP settings.

For Render deployments in which email delivery is re-enabled, provide the
appropriate provider configuration (for example `RESEND_API_KEY=<api key>`)
in the service's Environment settings and secure API keys in the platform's
secrets manager. Do not commit API keys or SMTP credentials to source control.

Local development continues to work without any external email provider; the
application still runs at `http://127.0.0.1:5000` and uses SQLite for data
storage.

## Emergency Administrator Recovery

The emergency recovery page is available to an authenticated Company
Administrator at **Settings → Users → Emergency Administrator Recovery** only
when `MASTER_ADMIN_KEY` is configured. Set this variable in Render's
Environment settings and keep its value in the platform's secret storage; do
not add it to source control. If it is unset, the recovery feature is disabled.

Each recovery operation requires the administrator's current account password
and the master key. The key is only compared with the environment value; it is
never used as a login password, saved in the database, placed in the session,
or displayed back in the page. Opening the recovery tools requires both
credentials and grants a five-minute session; each operation also rechecks
both credentials. Operations can reset a user's password, unlock
an account, require a password change at next login, and enable or disable an
account. User targets are scoped to the administrator's company, and each
attempt and successful action is recorded in that company's audit log with the
administrator, target, action, and timestamp. Account password hashes continue
to use the application's existing Werkzeug hashing.

For local testing, set `MASTER_ADMIN_KEY` in the environment before starting
`python app.py`. Do not reuse a production key in development.

Make a backup before replacing or migrating a database.

## Menu Items

The Menu Items module maintains saleable products, separate menu categories,
selling prices, recipe costs, active status, and per-item audit history.
First-run initialization creates the menu categories `Food` and `Beverages`.
Recipes link to raw, manufactured, or portioned stock items and calculate
their cost from the linked inventory items' current unit costs.

Menu item data can be imported from a spreadsheet saved as a UTF-8 CSV using
the Menu Items **Import CSV** action. The required columns are `Code`, `Name`,
`Type`, `Category`, and `Selling Price`; `Active` is optional and defaults to
Yes. Valid types are `Ordinary Type` and `Prep Screen Item`. Categories must
already exist and be active. The import template can be downloaded from the
import screen. Recipe lines are added separately after importing menu items.

Inventory sale and refund processing is available as a transactional service
foundation for future Sales/POS integration. It records stock movements and
uses the original sale's recipe snapshot when processing refunds. This release
does not include a Sales or POS screen.

## Distribution

Email or otherwise distribute only the final:

```text
release\KitchenFactorySetup.exe
```

The recipient runs the installer, accepts the Windows prompts, and launches
Kitchen Factory from the Desktop or Start Menu. Do not distribute the source
folder as the normal user installation method.

For release integrity, publish the SHA-256 hash alongside the installer:

```powershell
Get-FileHash .\release\KitchenFactorySetup.exe -Algorithm SHA256
```

## Troubleshooting

### The browser does not open

Open a browser manually and navigate to
`http://127.0.0.1:5000/login`. Confirm that Kitchen Factory is running from
Task Manager. Restart the application if the port is already in use.

### Port 5000 is already in use

Close the other local application using port 5000 and restart Kitchen Factory.
The Version 1.0.0 launcher intentionally uses the documented fixed local URL.

### Windows SmartScreen appears

Unsigned first-party executables can produce a SmartScreen warning. Verify
the installer hash and choose the Windows option to view more information and
run it. Code signing should be added for public distribution.

### Database cannot be created

Confirm that the current Windows user can write to
`%LOCALAPPDATA%\Kitchen Factory`. Do not install the database under
`Program Files`.

### Existing data is missing

Confirm that the existing database was copied to
`%LOCALAPPDATA%\Kitchen Factory\kitchen_factory.db` and that Kitchen Factory
was closed before copying it.

### A build fails

Delete `.venv`, `build`, and `dist`, recreate the virtual environment, install
`requirements.txt`, and rerun `build_windows.ps1`.

## Deployment checklist

- [ ] `KitchenFactorySetup.exe` is produced.
- [ ] Installer runs on a clean Windows test machine.
- [ ] Program Files installation completes.
- [ ] Desktop shortcut works.
- [ ] Start Menu shortcut works.
- [ ] Uninstall entry is present.
- [ ] Application starts without a console window.
- [ ] Browser opens automatically.
- [ ] Login page opens at `/login`.
- [ ] First-run database is created.
- [ ] A new company can register and its administrator can log in with email and password.
- [ ] A password reset link expires and cannot be reused.
- [ ] A second company cannot view or modify the first company's records.
- [ ] Existing database records survive migration and are assigned to the legacy workspace.
- [ ] User management is available only to Company Administrators.
- [ ] Stock Item Database works.
- [ ] Manufacturing System works.
- [ ] Portioning System works.
- [ ] Menu Items can be created, edited, searched, viewed, and exported.
- [ ] Menu categories are managed separately from stock categories.
- [ ] Recipe costs and menu item audit history are displayed.
- [ ] Reports work.
- [ ] Settings work.
- [ ] About page shows Version 1.0.0, Database Version 1.0, and the build date.
- [ ] Existing database migration is tested from a backup copy.
- [ ] Installer is tested without Python or VS Code installed.
- [ ] Installer hash is recorded for distribution.

## Release process

1. Run the automated tests:

   ```powershell
   python -m compileall -q .
   python -m pytest -q
   ```

2. Run `build_windows.ps1` on a clean release checkout.
3. Install `release\KitchenFactorySetup.exe` on a clean Windows machine.
4. Complete the deployment checklist.
5. Generate and record the SHA-256 hash.
6. Archive the installer, hash, source revision, and test results.
7. Distribute the installer to users.
