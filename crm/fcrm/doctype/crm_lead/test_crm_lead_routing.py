"""
Unit tests for lead routing helpers in crm_lead.py.

All frappe DB/ORM calls are mocked so no database or Frappe installation is
required.  The module-under-test (crm_lead) imports frappe at module level, so
we inject a fake `frappe` package into sys.modules before the first import.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Bootstrap a fake `frappe` hierarchy so the module can be imported standalone
# ---------------------------------------------------------------------------

def _make_fake_frappe():
    frappe_mod = types.ModuleType("frappe")
    frappe_mod.get_all = MagicMock()
    frappe_mod.get_doc = MagicMock()
    frappe_mod.get_cached_doc = MagicMock()
    frappe_mod.get_cached_value = MagicMock()
    frappe_mod.throw = MagicMock()
    frappe_mod.session = MagicMock()
    frappe_mod.whitelist = lambda fn=None, **kw: (fn if callable(fn) else lambda f: f)
    frappe_mod._ = lambda x: x
    frappe_mod.ValidationError = Exception
    frappe_mod.PermissionError = Exception

    db = MagicMock()
    frappe_mod.db = db

    share = MagicMock()
    frappe_mod.share = share

    # sub-modules that crm_lead imports transitively
    for sub in [
        "frappe.tests",
        "frappe.tests.utils",
        "frappe.model",
        "frappe.model.document",
        "frappe.desk",
        "frappe.desk.form",
        "frappe.desk.form.assign_to",
        "frappe.utils",
        "frappe.types",
    ]:
        mod = types.ModuleType(sub)
        sys.modules.setdefault(sub, mod)

    # frappe.model.document.Document
    sys.modules["frappe.model.document"].Document = object
    # frappe.desk.form.assign_to.add
    sys.modules["frappe.desk.form.assign_to"].add = MagicMock()
    # frappe.utils helpers used in crm_lead
    sys.modules["frappe.utils"].has_gravatar = MagicMock(return_value=None)
    sys.modules["frappe.utils"].validate_email_address = MagicMock()

    return frappe_mod


_fake_frappe = _make_fake_frappe()
sys.modules["frappe"] = _fake_frappe


# Stub out crm internal dependencies so the import chain resolves
def _stub_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


_stub_module(
    "crm.fcrm.doctype.crm_service_level_agreement.utils",
    get_sla=MagicMock(return_value=None),
)
_stub_module(
    "crm.fcrm.doctype.crm_status_change_log.crm_status_change_log",
    add_status_change_log=MagicMock(),
)
_stub_module(
    "crm.fcrm.doctype.utils",
    add_or_remove_lost_reason_section_in_sidepanel=MagicMock(),
)

# Ensure the crm package hierarchy exists
for pkg in ["crm", "crm.fcrm", "crm.fcrm.doctype", "crm.fcrm.doctype.crm_lead"]:
    sys.modules.setdefault(pkg, types.ModuleType(pkg))

# Ensure the routing rule package and leaf module exist so the import works.
# We register a real stub module at the leaf path; Python's import machinery
# will use it directly instead of trying to find it on disk.
_rr_pkg_name = "crm.fcrm.doctype.crm_lead_routing_rule"
_rr_mod_name = "crm.fcrm.doctype.crm_lead_routing_rule.crm_lead_routing_rule"

# The package stub must be a module that acts as a package (has __path__)
_rr_pkg = types.ModuleType(_rr_pkg_name)
_rr_pkg.__path__ = []  # marks it as a package
_rr_pkg.__package__ = _rr_pkg_name
sys.modules[_rr_pkg_name] = _rr_pkg

# The leaf stub will be populated after we define CRMLeadRoutingRule below;
# reserve the slot now so importlib won't try to find it on disk.
_rr_leaf = types.ModuleType(_rr_mod_name)
sys.modules[_rr_mod_name] = _rr_leaf

# ---------------------------------------------------------------------------
# Now it is safe to import the actual modules under test
# ---------------------------------------------------------------------------

from crm.fcrm.doctype.crm_lead.crm_lead import (  # noqa: E402
    _auto_assign_lead,
    _find_routing_rule,
    _pick_next_staff,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_lead(**kwargs):
    """Return a mock lead object with sensible defaults."""
    defaults = {
        "name": "CRM-LEAD-0001",
        "lead_owner": None,
        "branch": "HN",
        "province": "Hanoi",
        "high_school": None,
    }
    defaults.update(kwargs)
    lead = MagicMock()
    for k, v in defaults.items():
        setattr(lead, k, v)
    # flags.get must return falsy by default so skip_routing guard doesn't trigger
    lead.flags = MagicMock()
    lead.flags.get.return_value = False
    return lead


def _make_staff_row(user):
    row = MagicMock()
    row.user = user
    return row


# ---------------------------------------------------------------------------
# _auto_assign_lead — early-exit scenarios (tests 1-3)
# ---------------------------------------------------------------------------

class TestAutoAssignLeadSkipConditions(unittest.TestCase):

    def setUp(self):
        # Reset frappe mocks before each test
        _fake_frappe.get_all.reset_mock()
        _fake_frappe.db.set_value.reset_mock()
        _fake_frappe.share.add_docshare.reset_mock()

    @patch("crm.fcrm.doctype.crm_lead.crm_lead._find_routing_rule")
    def test_skips_when_lead_owner_already_set(self, mock_find):
        """Test 1: skip when lead_owner is populated."""
        lead = _make_lead(lead_owner="staff@example.com")
        _auto_assign_lead(lead)
        mock_find.assert_not_called()

    @patch("crm.fcrm.doctype.crm_lead.crm_lead._find_routing_rule")
    def test_skips_when_branch_is_blank(self, mock_find):
        """Test 2: skip when branch is empty string."""
        lead = _make_lead(branch="", lead_owner=None)
        _auto_assign_lead(lead)
        mock_find.assert_not_called()

    @patch("crm.fcrm.doctype.crm_lead.crm_lead._find_routing_rule")
    def test_skips_when_province_is_blank(self, mock_find):
        """Test 3: skip when province is empty string."""
        lead = _make_lead(province="", lead_owner=None)
        _auto_assign_lead(lead)
        mock_find.assert_not_called()

    @patch("crm.fcrm.doctype.crm_lead.crm_lead._find_routing_rule")
    def test_skips_when_branch_is_none(self, mock_find):
        lead = _make_lead(branch=None, lead_owner=None)
        _auto_assign_lead(lead)
        mock_find.assert_not_called()

    @patch("crm.fcrm.doctype.crm_lead.crm_lead._find_routing_rule")
    def test_skips_when_province_is_none(self, mock_find):
        lead = _make_lead(province=None, lead_owner=None)
        _auto_assign_lead(lead)
        mock_find.assert_not_called()


# ---------------------------------------------------------------------------
# _find_routing_rule (tests 4-6)
# ---------------------------------------------------------------------------

class TestFindRoutingRule(unittest.TestCase):

    def setUp(self):
        _fake_frappe.get_all.reset_mock()

    def test_returns_school_specific_rule_when_school_matches(self):
        """Test 4: school-specific rule has priority over province rule."""
        school_rule = {"name": "RULE-SCHOOL-001", "round_robin_index": 0}
        province_rule = {"name": "RULE-PROVINCE-001", "round_robin_index": 0}

        def get_all_side_effect(doctype, filters=None, **kw):
            # The first call uses the school filter (not an "in" operator)
            school_val = filters.get("school") if filters else None
            if isinstance(school_val, str) and school_val not in ("", None):
                return [school_rule]
            return [province_rule]

        _fake_frappe.get_all.side_effect = get_all_side_effect

        result = _find_routing_rule("HN", "Hanoi", "THPT-ABC")
        self.assertEqual(result["name"], "RULE-SCHOOL-001")

    def test_falls_back_to_province_rule_when_no_school_match(self):
        """Test 5: fall back to province rule when school-specific lookup fails."""

        def get_all_side_effect(doctype, filters=None, **kw):
            school_val = filters.get("school") if filters else None
            if isinstance(school_val, str) and school_val not in ("", None):
                return []
            return [{"name": "RULE-PROVINCE-001", "round_robin_index": 0}]

        _fake_frappe.get_all.side_effect = get_all_side_effect

        result = _find_routing_rule("HN", "Hanoi", "THPT-UNKNOWN")
        self.assertEqual(result["name"], "RULE-PROVINCE-001")

    def test_returns_none_when_no_rules_match(self):
        """Test 6: return None when no rules exist for the branch/province."""
        _fake_frappe.get_all.return_value = []
        _fake_frappe.get_all.side_effect = None

        result = _find_routing_rule("HN", "Hanoi", None)
        self.assertIsNone(result)

    def test_returns_none_when_no_rules_match_with_school(self):
        _fake_frappe.get_all.return_value = []
        _fake_frappe.get_all.side_effect = None

        result = _find_routing_rule("HN", "Hanoi", "THPT-X")
        self.assertIsNone(result)

    def test_falls_back_to_province_rule_when_no_school_provided(self):
        province_rule = {"name": "RULE-PROVINCE-001", "round_robin_index": 0}
        _fake_frappe.get_all.return_value = [province_rule]
        _fake_frappe.get_all.side_effect = None

        result = _find_routing_rule("HN", "Hanoi", None)
        _fake_frappe.get_all.assert_called_once()
        self.assertEqual(result["name"], "RULE-PROVINCE-001")


# ---------------------------------------------------------------------------
# _pick_next_staff (tests 7-8)
# ---------------------------------------------------------------------------

class TestPickNextStaff(unittest.TestCase):

    def setUp(self):
        _fake_frappe.get_doc.reset_mock()
        _fake_frappe.db.sql.reset_mock()
        _fake_frappe.db.sql.side_effect = None
        _fake_frappe.db.get_value.reset_mock()

    def test_returns_none_for_empty_staff_list(self):
        """Test 7: return None when staff list is empty."""
        rule_doc = MagicMock()
        rule_doc.staff = []
        _fake_frappe.get_doc.return_value = rule_doc

        result = _pick_next_staff("RULE-001")
        self.assertIsNone(result)
        _fake_frappe.db.sql.assert_not_called()

    def _setup_sql_for_index(self, new_index):
        """Configure db.sql mock: first call (UPDATE) returns None, second call (SELECT LAST_INSERT_ID) returns [[new_index]]."""
        call_count = [0]
        def sql_side_effect(query, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return None  # UPDATE
            return [[new_index]]  # SELECT LAST_INSERT_ID()
        _fake_frappe.db.sql.side_effect = sql_side_effect

    def test_round_robin_first_call_returns_staff_0(self):
        """Test 8a: first increment → index=1 → slot=0 → staff[0]."""
        staff = [_make_staff_row("alice@example.com"), _make_staff_row("bob@example.com")]
        rule_doc = MagicMock()
        rule_doc.staff = staff
        _fake_frappe.get_doc.return_value = rule_doc
        self._setup_sql_for_index(1)

        result = _pick_next_staff("RULE-001")
        self.assertEqual(result, "alice@example.com")

    def test_round_robin_second_call_returns_staff_1(self):
        """Test 8b: second increment → index=2 → slot=1 → staff[1]."""
        staff = [_make_staff_row("alice@example.com"), _make_staff_row("bob@example.com")]
        rule_doc = MagicMock()
        rule_doc.staff = staff
        _fake_frappe.get_doc.return_value = rule_doc
        self._setup_sql_for_index(2)

        result = _pick_next_staff("RULE-001")
        self.assertEqual(result, "bob@example.com")

    def test_round_robin_wraps_around(self):
        """index=3, 2 staff → slot=(3-1)%2=0 → alice again."""
        staff = [_make_staff_row("alice@example.com"), _make_staff_row("bob@example.com")]
        rule_doc = MagicMock()
        rule_doc.staff = staff
        _fake_frappe.get_doc.return_value = rule_doc
        self._setup_sql_for_index(3)

        result = _pick_next_staff("RULE-001")
        self.assertEqual(result, "alice@example.com")

    def test_sql_increment_called_with_rule_name(self):
        staff = [_make_staff_row("alice@example.com")]
        rule_doc = MagicMock()
        rule_doc.staff = staff
        _fake_frappe.get_doc.return_value = rule_doc
        self._setup_sql_for_index(1)

        _pick_next_staff("RULE-XYZ")
        # Two sql calls: UPDATE with LAST_INSERT_ID then SELECT LAST_INSERT_ID()
        self.assertEqual(_fake_frappe.db.sql.call_count, 2)
        update_args = _fake_frappe.db.sql.call_args_list[0][0]
        self.assertIn("RULE-XYZ", update_args)


# ---------------------------------------------------------------------------
# _auto_assign_lead — successful routing path (test 9)
# ---------------------------------------------------------------------------

class TestAutoAssignLeadSuccess(unittest.TestCase):

    def setUp(self):
        _fake_frappe.db.set_value.reset_mock()
        _fake_frappe.share.add_docshare.reset_mock()

    @patch("crm.fcrm.doctype.crm_lead.crm_lead._pick_next_staff")
    @patch("crm.fcrm.doctype.crm_lead.crm_lead._find_routing_rule")
    def test_calls_set_value_add_docshare_and_assign_agent(self, mock_find, mock_pick):
        """Test 9: successful routing triggers all three side-effects."""
        lead = _make_lead(lead_owner=None, branch="HN", province="Hanoi")
        mock_find.return_value = {"name": "RULE-001", "round_robin_index": 0}
        mock_pick.return_value = "staff@example.com"

        _auto_assign_lead(lead)

        _fake_frappe.db.set_value.assert_called_once_with(
            "CRM Lead", lead.name, "lead_owner", "staff@example.com", update_modified=False
        )
        _fake_frappe.share.add_docshare.assert_called_once_with(
            "CRM Lead", lead.name, "staff@example.com",
            read=1, write=1, share=0, everyone=0, notify=0,
            flags={"ignore_share_permission": True},
        )
        lead.assign_agent.assert_called_once_with("staff@example.com")

    @patch("crm.fcrm.doctype.crm_lead.crm_lead._pick_next_staff")
    @patch("crm.fcrm.doctype.crm_lead.crm_lead._find_routing_rule")
    def test_does_nothing_when_no_rule_found(self, mock_find, mock_pick):
        lead = _make_lead(lead_owner=None, branch="HN", province="Hanoi")
        mock_find.return_value = None

        _auto_assign_lead(lead)

        mock_pick.assert_not_called()
        _fake_frappe.db.set_value.assert_not_called()
        _fake_frappe.share.add_docshare.assert_not_called()
        lead.assign_agent.assert_not_called()

    @patch("crm.fcrm.doctype.crm_lead.crm_lead._pick_next_staff")
    @patch("crm.fcrm.doctype.crm_lead.crm_lead._find_routing_rule")
    def test_does_nothing_when_no_staff_returned(self, mock_find, mock_pick):
        lead = _make_lead(lead_owner=None, branch="HN", province="Hanoi")
        mock_find.return_value = {"name": "RULE-001", "round_robin_index": 0}
        mock_pick.return_value = None

        _auto_assign_lead(lead)

        _fake_frappe.db.set_value.assert_not_called()
        _fake_frappe.share.add_docshare.assert_not_called()
        lead.assign_agent.assert_not_called()

    @patch("crm.fcrm.doctype.crm_lead.crm_lead._pick_next_staff")
    @patch("crm.fcrm.doctype.crm_lead.crm_lead._find_routing_rule")
    def test_passes_high_school_attribute_to_find_routing_rule(self, mock_find, mock_pick):
        lead = _make_lead(lead_owner=None, branch="HN", province="Hanoi", high_school="THPT-ABC")
        mock_find.return_value = None

        _auto_assign_lead(lead)

        mock_find.assert_called_once_with("HN", "Hanoi", "THPT-ABC")


# ---------------------------------------------------------------------------
# CRMLeadRoutingRule.validate — duplicate detection
# ---------------------------------------------------------------------------

class TestCRMLeadRoutingRuleValidate(unittest.TestCase):

    def _import_routing_rule_class(self):
        import importlib.util, os
        mod_name = "crm.fcrm.doctype.crm_lead_routing_rule.crm_lead_routing_rule"
        if hasattr(sys.modules.get(mod_name), "CRMLeadRoutingRule"):
            return sys.modules[mod_name].CRMLeadRoutingRule
        # Load directly from file so we bypass package-path resolution
        src = os.path.join(
            os.path.dirname(__file__),
            "..", "crm_lead_routing_rule", "crm_lead_routing_rule.py",
        )
        src = os.path.normpath(src)
        spec = importlib.util.spec_from_file_location(mod_name, src)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        return mod.CRMLeadRoutingRule

    def _make_rule(self, name="RULE-NEW", branch="HN", province="Hanoi", school=""):
        cls = self._import_routing_rule_class()
        rule = cls.__new__(cls)
        rule.name = name
        rule.branch = branch
        rule.province = province
        rule.school = school
        return rule

    def setUp(self):
        _fake_frappe.db.get_value.reset_mock()
        _fake_frappe.throw.reset_mock()
        _fake_frappe.throw.side_effect = None

    def test_throws_when_duplicate_rule_exists(self):
        rule = self._make_rule()
        _fake_frappe.db.get_value.return_value = "RULE-EXISTING"

        _fake_frappe.throw.side_effect = Exception("duplicate")
        with self.assertRaises(Exception):
            rule.validate()

        _fake_frappe.throw.assert_called_once()

    def test_no_throw_when_no_duplicate(self):
        rule = self._make_rule()
        _fake_frappe.db.get_value.return_value = None

        rule.validate()

        _fake_frappe.throw.assert_not_called()

    def test_school_scope_included_in_throw_message(self):
        rule = self._make_rule(school="THPT-ABC")
        _fake_frappe.db.get_value.return_value = "RULE-EXISTING"

        captured = {}

        def throw_side_effect(msg):
            captured["msg"] = msg
            raise Exception(msg)

        _fake_frappe.throw.side_effect = throw_side_effect

        with self.assertRaises(Exception):
            rule.validate()

        self.assertIn("THPT-ABC", captured.get("msg", ""))


if __name__ == "__main__":
    unittest.main()
