import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.admissions_dashboard_auth import (
	DashboardAccessDenied,
	check_dashboard_access,
	get_campus_scope,
	get_campus_scoped_staff_names,
	require_dashboard_access,
)


class TestAdmissionsDashboardAuth(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._anchor_campus = self._make_campus("_Test Dashboard Auth Anchor Campus")

	def tearDown(self):
		self._cleanup_campus(self._anchor_campus)

	# ---------------------------------------------------------------- require_dashboard_access

	def test_require_dashboard_access_admin_allowed_everywhere(self):
		for dashboard in ("sale", "digital_marketing", "offline_marketing"):
			require_dashboard_access(dashboard, user_roles={"Administrator"})

	def test_require_dashboard_access_sale_role_allowed_for_sale(self):
		for role in ("Sale", "Lead Sales", "CTV-Sale", "Counseller", "Sales User", "Sales Manager", "Team Leader"):
			require_dashboard_access("sale", user_roles={role})

	def test_require_dashboard_access_sale_role_denied_for_offline_marketing(self):
		with self.assertRaises(DashboardAccessDenied):
			require_dashboard_access("offline_marketing", user_roles={"Sale"})

	def test_require_dashboard_access_retired_sales_role_denied(self):
		with self.assertRaises(DashboardAccessDenied):
			require_dashboard_access("sale", user_roles={"Sales"})

	def test_require_dashboard_access_promoter_allowed_for_offline_marketing(self):
		require_dashboard_access("offline_marketing", user_roles={"Promoter-PR"})

	def test_require_dashboard_access_marketing_allowed_for_marketing_dashboards(self):
		for dashboard in ("digital_marketing", "offline_marketing"):
			require_dashboard_access(dashboard, user_roles={"Marketing"})

	def test_require_dashboard_access_promoter_denied_for_sale(self):
		with self.assertRaises(DashboardAccessDenied):
			require_dashboard_access("sale", user_roles={"Promoter-PR"})

	def test_require_dashboard_access_team_leader_allowed_for_digital_marketing(self):
		require_dashboard_access("digital_marketing", user_roles={"Team Leader"})

	def test_require_dashboard_access_non_team_leader_denied_for_digital_marketing(self):
		with self.assertRaises(DashboardAccessDenied):
			require_dashboard_access("digital_marketing", user_roles={"Sale"})

	def test_require_dashboard_access_no_roles_denied(self):
		with self.assertRaises(DashboardAccessDenied):
			require_dashboard_access("sale", user_roles=set())

	def test_require_dashboard_access_unknown_dashboard_raises_keyerror(self):
		with self.assertRaises(KeyError):
			require_dashboard_access("nonexistent_dashboard", user_roles={"Administrator"})

	# ---------------------------------------------------------------------- get_campus_scope

	def test_get_campus_scope_administrator_returns_none(self):
		self.assertIsNone(get_campus_scope(user_roles={"Administrator"}))

	def test_get_campus_scope_system_manager_returns_none(self):
		self.assertIsNone(get_campus_scope(user_roles={"System Manager"}))

	def test_get_campus_scope_no_crm_staff_raises(self):
		with self.assertRaises(DashboardAccessDenied):
			get_campus_scope(user="_test_no_staff_user@example.com", user_roles={"Sale"})

	def test_get_campus_scope_staff_without_campus_raises(self):
		user, staff = self._make_user_and_staff("_test_no_campus", campus="")
		try:
			with self.assertRaises(DashboardAccessDenied):
				get_campus_scope(user=user, user_roles={"Sale"})
		finally:
			self._cleanup_user_and_staff(user, staff)

	def test_get_campus_scope_returns_staff_campus(self):
		campus = self._make_campus("_Test Dashboard Campus")
		user, staff = self._make_user_and_staff("_test_with_campus", campus=campus)
		try:
			self.assertEqual(get_campus_scope(user=user, user_roles={"Sale"}), campus)
		finally:
			self._cleanup_user_and_staff(user, staff)
			self._cleanup_campus(campus)

	# --------------------------------------------------------- get_campus_scoped_staff_names

	def test_get_campus_scoped_staff_names(self):
		campus = self._make_campus("_Test Dashboard Campus 2")
		user1, staff1 = self._make_user_and_staff("_test_scoped_1", campus=campus)
		user2, staff2 = self._make_user_and_staff("_test_scoped_2", campus=campus)
		try:
			names = get_campus_scoped_staff_names(campus)
			self.assertIn(staff1, names)
			self.assertIn(staff2, names)
		finally:
			self._cleanup_user_and_staff(user1, staff1)
			self._cleanup_user_and_staff(user2, staff2)
			self._cleanup_campus(campus)

	def test_get_campus_scoped_staff_names_empty_for_unused_campus(self):
		campus = self._make_campus("_Test Dashboard Campus Empty")
		try:
			self.assertEqual(get_campus_scoped_staff_names(campus), [])
		finally:
			self._cleanup_campus(campus)

	# ------------------------------------------------------------------- check_dashboard_access

	def test_check_dashboard_access_admin_returns_none(self):
		frappe.set_user("Administrator")
		self.assertIsNone(check_dashboard_access("sale", user="Administrator"))

	def test_check_dashboard_access_denies_wrong_role(self):
		campus = self._make_campus("_Test Dashboard Campus 3")
		user, staff = self._make_user_and_staff("_test_check_wrong_role", campus=campus, roles=["Marketing"])
		try:
			with self.assertRaises(DashboardAccessDenied):
				check_dashboard_access("sale", user=user)
		finally:
			self._cleanup_user_and_staff(user, staff)
			self._cleanup_campus(campus)

	def test_check_dashboard_access_scoped_staff_for_allowed_role(self):
		campus = self._make_campus("_Test Dashboard Campus 4")
		user, staff = self._make_user_and_staff("_test_check_allowed_role", campus=campus, roles=["Sale"])
		try:
			names = check_dashboard_access("sale", user=user)
			self.assertIn(staff, names)
		finally:
			self._cleanup_user_and_staff(user, staff)
			self._cleanup_campus(campus)

	# ---------------------------------------------------------------------------- helpers

	def _make_campus(self, name):
		if frappe.db.exists("CRM Campus", name):
			frappe.delete_doc("CRM Campus", name, force=True)
		doc = frappe.get_doc({"doctype": "CRM Campus", "campus_name": name})
		doc.insert(ignore_permissions=True)
		return doc.name

	def _cleanup_campus(self, campus):
		if campus and frappe.db.exists("CRM Campus", campus):
			frappe.delete_doc("CRM Campus", campus, force=True)

	def _make_user_and_staff(self, prefix, campus=None, roles=None):
		email = f"{prefix}@example.com"
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True)
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": prefix,
				"send_welcome_email": 0,
				"roles": [{"role": role} for role in (roles or ["Sale"])],
			}
		)
		user.insert(ignore_permissions=True)

		department = self._get_or_create_department("_Test Dashboard Auth Dept")

		staff_name = f"_Test Staff {prefix}"
		if frappe.db.exists("CRM Staff", staff_name):
			frappe.delete_doc("CRM Staff", staff_name, force=True)
		staff = frappe.get_doc(
			{
				"doctype": "CRM Staff",
				"full_name": staff_name,
				"user": email,
				"department": department,
				# campus is reqd on insert; the anchor value satisfies validation and is
				# overwritten below with the per-test value (which may be "" or None).
				"campus": self._anchor_campus,
			}
		)
		staff.insert(ignore_permissions=True)
		# CRM Staff.on_update overwrites `campus` to match `department.campus` (see
		# crm_staff.py _sync_campus_user_permission wiring), which would clobber the
		# per-test campus/no-campus value we deliberately set above. Force the raw DB
		# value afterward — get_campus_scope reads via frappe.db.get_value, so this is
		# sufficient to exercise it without fighting the controller's sync behavior.
		frappe.db.set_value("CRM Staff", staff.name, "campus", campus, update_modified=False)
		return email, staff.name

	def _cleanup_user_and_staff(self, user, staff):
		if staff and frappe.db.exists("CRM Staff", staff):
			frappe.delete_doc("CRM Staff", staff, force=True)
		if user and frappe.db.exists("User", user):
			frappe.delete_doc("User", user, force=True)

	def _get_or_create_department(self, name):
		if not frappe.db.exists("CRM Department", name):
			frappe.get_doc(
				{
					"doctype": "CRM Department",
					"department_name": name,
					"campus": self._anchor_campus,
				}
			).insert(ignore_permissions=True)
		return name
