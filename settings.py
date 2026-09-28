"""Centralised application settings and conversion helpers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SettingDefinition:
    key: str
    default: str
    label: str
    section: str
    kind: str = "text"
    description: str = ""


SETTING_DEFINITIONS = (
    SettingDefinition("allow_negative_stock", "0", "Allow negative stock", "Inventory", "bool",
                      "Let the kitchen continue a transaction when there is not enough stock available. Use this only when shortages are tracked separately."),
    SettingDefinition("calculator_mode", "0", "Calculator mode", "General", "bool",
                      "Save manufacturing and portioning calculations without changing stock quantities. This is useful for planning or costing."),
    SettingDefinition("manufacturing_require_notes", "0", "Require manufacturing notes", "Manufacturing", "bool",
                      "Ask the user to record a note before saving a manufacturing transaction."),
    SettingDefinition("manufacturing_require_confirmation", "0", "Require manufacturing confirmation", "Manufacturing", "bool",
                      "Ask the user to confirm the summary before a manufacturing transaction is processed."),
    SettingDefinition("manufacturing_auto_cost", "0", "Automatically update output cost", "Manufacturing", "bool",
                      "Set the manufactured item's cost per unit to the calculated recipe cost after processing."),
    SettingDefinition("portioning_require_waste_reason", "0", "Require waste reason", "Portioning", "bool",
                      "Ask the user to explain why waste was recorded during portioning."),
    SettingDefinition("portioning_minimum_yield", "0", "Minimum yield warning (%)", "Portioning", "text",
                      "Show a warning when the usable yield falls below this percentage. Enter 0 to turn the warning off."),
    SettingDefinition("appearance_mode", "light", "Appearance mode", "Appearance", "choice",
                      "Choose whether the application uses a light or dark colour contrast."),
    SettingDefinition("appearance_colour_scheme", "kitchen_green", "Colour scheme", "Appearance", "choice",
                      "Choose the colour used for buttons, highlights, and active navigation."),
    SettingDefinition("reporting_default_rows", "25", "Default report rows", "General", "choice",
                      "Choose how many stock rows appear on each report page."),
    SettingDefinition("reporting_currency", "R", "Currency symbol", "General",
                      "The symbol shown beside costs in reports and summaries."),
    SettingDefinition("reporting_company_name", "Kitchen Factory", "Company name", "General",
                      "The name printed at the top of reports."),
    SettingDefinition("reporting_default_export", "csv", "Default export format", "General", "choice",
                      "Choose the file format used when a report is exported by default."),
    SettingDefinition("reporting_logo_placeholder", "", "Logo placeholder", "General",
                      "Optional text or image reference shown as the report logo placeholder."),
    SettingDefinition("audit_level", "standard", "Audit level", "General", "choice",
                      "Choose how much detail is recorded in the activity history."),
    SettingDefinition("audit_retention_days", "0", "Audit retention (days)", "General", "choice",
                      "Choose how long activity history is displayed. Enter 0 to keep it indefinitely."),
    SettingDefinition("audit_enabled", "1", "Enable audit logging", "General", "bool",
                      "Record important changes and transactions for management review."),
)

SETTING_DEFAULTS = {item.key: item.default for item in SETTING_DEFINITIONS}

SETTING_CHOICES = {
    "appearance_mode": {"light", "dark"},
    "appearance_colour_scheme": {"kitchen_green", "kitchen_blue"},
    "reporting_default_export": {"csv", "xlsx", "pdf"},
    "audit_level": {"minimal", "standard", "detailed"},
}


def setting_value(key, value=None):
    """Return a normalised setting value, falling back to the central default."""
    if value is None:
        return SETTING_DEFAULTS.get(key, "")
    return str(value)


def setting_bool(key, value=None):
    return setting_value(key, value).lower() in {"1", "true", "yes", "on"}


def setting_int(key, value=None):
    try:
        return int(setting_value(key, value))
    except (TypeError, ValueError):
        return int(SETTING_DEFAULTS.get(key, "0"))


def settings_by_section(values):
    return {
        section: [
            {"definition": definition, "value": setting_value(definition.key, values.get(definition.key))}
            for definition in SETTING_DEFINITIONS if definition.section == section
        ]
        for section in dict.fromkeys(item.section for item in SETTING_DEFINITIONS)
    }
