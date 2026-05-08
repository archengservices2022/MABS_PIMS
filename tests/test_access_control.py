import unittest

from access_control import (
    ACTION_CONVERT_QUOTE_TO_INVOICE,
    ACTION_CONVERT_QUOTE_TO_PROJECT,
    ACTION_CREATE_EDIT_QUOTES,
    PAGE_DASHBOARD,
    PAGE_FINANCIAL,
    PAGE_PROJECTS,
    PAGE_QUOTES,
    PAGE_SETTINGS,
    allowed_page_keys_for_role,
    allowed_stack_pages_for_role,
    can_access_page,
    can_perform_action,
    first_allowed_stack_page,
    normalize_role,
    profile_is_active,
)


class AccessControlTests(unittest.TestCase):
    def test_admin_can_access_every_workspace_page_and_settings(self):
        self.assertEqual(
            allowed_stack_pages_for_role("admin"),
            [PAGE_DASHBOARD, PAGE_QUOTES, PAGE_PROJECTS, PAGE_FINANCIAL],
        )
        self.assertTrue(can_access_page("admin", PAGE_SETTINGS))

    def test_sales_only_lands_on_and_accesses_quote_forms(self):
        self.assertEqual(allowed_page_keys_for_role("sales"), ["quotes"])
        self.assertEqual(allowed_stack_pages_for_role("sales"), [PAGE_QUOTES])
        self.assertEqual(first_allowed_stack_page("sales"), PAGE_QUOTES)
        self.assertTrue(can_access_page("sales", PAGE_QUOTES))
        self.assertFalse(can_access_page("sales", PAGE_PROJECTS))
        self.assertFalse(can_access_page("sales", PAGE_FINANCIAL))
        self.assertFalse(can_access_page("sales", PAGE_SETTINGS))

    def test_actions_are_separate_from_page_visibility(self):
        self.assertTrue(can_perform_action("sales", ACTION_CREATE_EDIT_QUOTES))
        self.assertFalse(can_perform_action("sales", ACTION_CONVERT_QUOTE_TO_PROJECT))
        self.assertFalse(can_perform_action("sales", ACTION_CONVERT_QUOTE_TO_INVOICE))
        self.assertTrue(can_perform_action("projects", ACTION_CONVERT_QUOTE_TO_PROJECT))
        self.assertTrue(can_perform_action("projects", ACTION_CONVERT_QUOTE_TO_INVOICE))

    def test_projects_and_finance_have_separate_workspaces(self):
        self.assertEqual(allowed_stack_pages_for_role("projects"), [PAGE_PROJECTS])
        self.assertFalse(can_access_page("projects", PAGE_QUOTES))
        self.assertEqual(allowed_stack_pages_for_role("finance"), [PAGE_FINANCIAL])
        self.assertFalse(can_access_page("finance", PAGE_PROJECTS))

    def test_unknown_roles_normalize_to_sales(self):
        self.assertEqual(normalize_role("unexpected"), "sales")
        self.assertEqual(allowed_stack_pages_for_role("unexpected"), [PAGE_QUOTES])

    def test_profile_active_flag_blocks_explicit_false_values(self):
        self.assertTrue(profile_is_active({}))
        self.assertTrue(profile_is_active({"active": True}))
        self.assertFalse(profile_is_active({"active": False}))
        self.assertFalse(profile_is_active({"active": "disabled"}))


if __name__ == "__main__":
    unittest.main()
