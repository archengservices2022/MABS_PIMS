"""Role capability rules for the PIMS workspace.

Roles are defined in business terms first. UI page indexes are only used at the
edge where MainWindow talks to QStackedWidget and Sidebar.
"""

PAGE_DASHBOARD = 0
PAGE_QUOTES    = 1
PAGE_PROJECTS  = 2
PAGE_INVOICING = 3   # Invoice Management + Client tabs
PAGE_FINANCIAL = 4
PAGE_SETTINGS  = 99

PAGE_DASHBOARD_KEY = "dashboard"
PAGE_QUOTES_KEY    = "quotes"
PAGE_PROJECTS_KEY  = "projects"
PAGE_INVOICING_KEY = "invoicing"
PAGE_FINANCIAL_KEY = "financial"
PAGE_SETTINGS_KEY  = "settings"

PAGE_INDEX_BY_KEY = {
    PAGE_DASHBOARD_KEY: PAGE_DASHBOARD,
    PAGE_QUOTES_KEY:    PAGE_QUOTES,
    PAGE_PROJECTS_KEY:  PAGE_PROJECTS,
    PAGE_INVOICING_KEY: PAGE_INVOICING,
    PAGE_FINANCIAL_KEY: PAGE_FINANCIAL,
    PAGE_SETTINGS_KEY:  PAGE_SETTINGS,
}
PAGE_KEY_BY_INDEX  = {index: key for key, index in PAGE_INDEX_BY_KEY.items()}
STACK_PAGE_KEYS    = (
    PAGE_DASHBOARD_KEY, PAGE_QUOTES_KEY,
    PAGE_PROJECTS_KEY, PAGE_INVOICING_KEY, PAGE_FINANCIAL_KEY,
)

ACTION_CREATE_EDIT_QUOTES        = "create_edit_quotes"
ACTION_CONVERT_QUOTE_TO_PROJECT  = "convert_quote_to_project"
ACTION_CONVERT_QUOTE_TO_INVOICE  = "convert_quote_to_invoice"

DEFAULT_ROLE = "sales"

ROLE_ALLOWED_PAGE_KEYS = {
    "admin": (
        PAGE_DASHBOARD_KEY,
        PAGE_QUOTES_KEY,
        PAGE_PROJECTS_KEY,
        PAGE_INVOICING_KEY,
        PAGE_FINANCIAL_KEY,
        PAGE_SETTINGS_KEY,
    ),
    "sales":    (PAGE_QUOTES_KEY,),
    "projects": (PAGE_PROJECTS_KEY, PAGE_INVOICING_KEY),
    "finance":  (PAGE_FINANCIAL_KEY,),
}

ROLE_ALLOWED_ACTIONS = {
    "admin": (
        ACTION_CREATE_EDIT_QUOTES,
        ACTION_CONVERT_QUOTE_TO_PROJECT,
        ACTION_CONVERT_QUOTE_TO_INVOICE,
    ),
    "sales":    (ACTION_CREATE_EDIT_QUOTES,),
    "projects": (ACTION_CONVERT_QUOTE_TO_PROJECT, ACTION_CONVERT_QUOTE_TO_INVOICE),
    "finance":  (),
}

VALID_ROLES = set(ROLE_ALLOWED_PAGE_KEYS)


def normalize_role(role: str) -> str:
    clean_role = str(role or DEFAULT_ROLE).strip().lower()
    return clean_role if clean_role in VALID_ROLES else DEFAULT_ROLE


def page_key_for_index(page_index: int) -> str:
    return PAGE_KEY_BY_INDEX.get(page_index, "")


def allowed_page_keys_for_role(role: str):
    return list(ROLE_ALLOWED_PAGE_KEYS.get(normalize_role(role), ROLE_ALLOWED_PAGE_KEYS[DEFAULT_ROLE]))


def allowed_pages_for_role(role: str):
    return [PAGE_INDEX_BY_KEY[key] for key in allowed_page_keys_for_role(role)]


def allowed_stack_pages_for_role(role: str):
    return [
        PAGE_INDEX_BY_KEY[key]
        for key in allowed_page_keys_for_role(role)
        if key in STACK_PAGE_KEYS
    ]


def first_allowed_stack_page(role: str) -> int:
    pages = allowed_stack_pages_for_role(role)
    return pages[0] if pages else PAGE_QUOTES


def can_access_page(role: str, page_index: int) -> bool:
    return page_key_for_index(page_index) in allowed_page_keys_for_role(role)


def can_perform_action(role: str, action: str) -> bool:
    allowed_actions = ROLE_ALLOWED_ACTIONS.get(normalize_role(role), ROLE_ALLOWED_ACTIONS[DEFAULT_ROLE])
    return action in allowed_actions


def profile_is_active(profile: dict) -> bool:
    value = (profile or {}).get("active", True)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "no", "inactive", "disabled"}
    return bool(value)
