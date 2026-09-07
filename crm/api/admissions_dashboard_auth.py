import frappe

# Shared role-gate + campus-tenancy helper for the Sale / Digital Marketing / Offline
# Marketing / Admissions Director dashboard aggregation APIs, all in
# crm/api/admissions_dashboard.py.
#
# Deliberately NOT a copy of crm/api/dashboard.py's @sales_user_only: that gate checks
# for the pre-migration Sales roles. The canonical operating roles are Sale,
# Lead Sale, Marketing, and Admissions Director.

ADMIN_ROLES = {"Administrator", "System Manager", "Admissions Director"}

DASHBOARD_ROLE_GATES = {
	"sale": {"Sale", "CTV Sale", "Lead Sale", *ADMIN_ROLES},
	"digital_marketing": {"Marketing", "Lead Marketing", *ADMIN_ROLES},
	"offline_marketing": {"Marketing", "Promoter", "Lead Promoter", *ADMIN_ROLES},
	"admissions_director": {"Admissions Director", *ADMIN_ROLES},
}


class DashboardAccessDenied(frappe.PermissionError):
	pass


def require_dashboard_access(dashboard, user=None, user_roles=None):
	"""Fail-closed role gate. Raises DashboardAccessDenied if the user lacks any
	role in DASHBOARD_ROLE_GATES[dashboard]."""
	user = user or frappe.session.user
	allowed_roles = DASHBOARD_ROLE_GATES[dashboard]
	user_roles = set(user_roles) if user_roles is not None else set(frappe.get_roles(user))
	if not (allowed_roles & user_roles):
		frappe.throw(
			"Bạn không có quyền truy cập báo cáo này.",
			DashboardAccessDenied,
		)


def get_campus_scope(user=None, user_roles=None):
	"""Returns None for admin roles (no campus restriction — see all campuses).
	For every other role, returns the calling user's CRM Staff.campus.
	Fail-closed, mirroring CRM Student.get_permission_query_conditions: raises
	DashboardAccessDenied (not an unfiltered/all-campus query) if the user has no
	linked CRM Staff record or that record has no campus set.
	"""
	user = user or frappe.session.user
	user_roles = set(user_roles) if user_roles is not None else set(frappe.get_roles(user))

	if ADMIN_ROLES & user_roles:
		return None

	campus = frappe.db.get_value("CRM Staff", {"user": user}, "campus")
	if campus is None:
		frappe.throw(
			"Tài khoản chưa được liên kết với hồ sơ nhân viên (CRM Staff).",
			DashboardAccessDenied,
		)
	if not campus:
		frappe.throw(
			"Hồ sơ nhân viên chưa được gán cơ sở (campus).",
			DashboardAccessDenied,
		)

	return campus


def get_campus_scoped_staff_names(campus):
	"""CRM Staff names sharing the given campus — the join target for scoping
	CRM Student.assigned_to in new frappe.qb aggregation queries."""
	return frappe.db.get_all("CRM Staff", filters={"campus": campus}, pluck="name")


def check_dashboard_access(dashboard, user=None):
	"""Convenience entry point: role gate + campus scope in one call.
	Returns the campus-scoped CRM Staff name list, or None for admins (no scoping)."""
	user = user or frappe.session.user
	user_roles = set(frappe.get_roles(user))
	require_dashboard_access(dashboard, user, user_roles=user_roles)
	campus = get_campus_scope(user, user_roles=user_roles)
	if campus is None:
		return None
	staff_names = get_campus_scoped_staff_names(campus)
	if not staff_names:
		frappe.throw(
			"Không tìm thấy nhân viên nào thuộc cơ sở của bạn.",
			DashboardAccessDenied,
		)
	return staff_names
