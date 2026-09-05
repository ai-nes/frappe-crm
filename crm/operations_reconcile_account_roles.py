"""Apply the confirmed account-to-role reconciliation on a CRM site."""

from __future__ import annotations

import frappe


ROLE_BY_EMAIL = {
	"duydt11@fpt.edu.vn": "Admissions Director",
	"gianghh2@fpt.edu.vn": "Sale",
	"huettl@fpt.edu.vn": "Sale",
	"hauntt4@fpt.edu.vn": "Sale",
	"tuyendtb.fpt@gmail.com": "Sale",
	"manhtv17@fpt.edu.vn": "Lead Marketing",
	"ngoclh3@fpt.edu.vn": "Lead Promoter",
	"loilq6@fpt.edu.vn": "Promoter",
	"danhvt2@fpt.edu.vn": "Promoter",
	"dungntt44@fpt.edu.vn": "Promoter",
	"nhittt1909@gmail.com": "Marketing",
	"dattd4@fpt.edu.vn": "Promoter",
	"ngannth10@fpt.edu.vn": "Sale",
	"trunglb2@fpt.edu.vn": "Admissions Director",
	"tuyendtb@fpt.edu.vn": "Lead Sale",
	"liinhkhanh1810@gmail.com": "CTV Sale",
	"tuyensinhhcm@fpt.edu.vn": "CTV Sale",
}

CANONICAL_ROLES = frozenset(
	{
		"CTV Sale",
		"Sale",
		"Lead Sale",
		"Promoter",
		"Lead Promoter",
		"Marketing",
		"Lead Marketing",
		"Admissions Director",
		"Administrator",
	}
)
PLATFORM_ROLES = frozenset({"All", "Guest", "Desk User", "Website User", "System Manager"})
PROTECTED_USERS = frozenset(
	{"Administrator", "admin@gmail.com", "ngothanhdat4002@gmail.com", "nguyenquocan1010@gmail.com"}
)


def _set_roles(user: str, role: str) -> None:
	for row in frappe.get_all(
		"Has Role", filters={"parent": user, "parenttype": "User"}, fields=["name", "role"], limit_page_length=0
	):
		if row.role not in PLATFORM_ROLES and row.role != role:
			frappe.db.delete("Has Role", {"name": row.name})
	if not frappe.db.exists("Has Role", {"parent": user, "parenttype": "User", "role": role}):
		frappe.get_doc(
			{
				"doctype": "Has Role",
				"parent": user,
				"parenttype": "User",
				"parentfield": "roles",
				"role": role,
			}
		).insert(ignore_permissions=True)


def _normalize_protected_user(user: str) -> None:
	"""Keep technical accounts on Administrator only (plus Frappe primitives)."""
	for row in frappe.get_all(
		"Has Role", filters={"parent": user, "parenttype": "User"}, fields=["name", "role"], limit_page_length=0
	):
		if row.role in CANONICAL_ROLES and row.role != "Administrator":
			frappe.db.delete("Has Role", {"name": row.name})
	if not frappe.db.exists("Has Role", {"parent": user, "parenttype": "User", "role": "Administrator"}):
		_set_roles(user, "Administrator")


def apply() -> dict:
	users = frappe.get_all("User", filters={"enabled": 1, "user_type": "System User"}, pluck="name")
	changes = []
	protected = []
	missing = []
	for email, role in ROLE_BY_EMAIL.items():
		if email not in users:
			missing.append(email)
			continue
		_set_roles(email, role)
		changes.append({"user": email, "role": role})

	for user in users:
		if user in ROLE_BY_EMAIL or user in PROTECTED_USERS:
			if user in PROTECTED_USERS:
				_normalize_protected_user(user)
				protected.append(user)
			continue
		_set_roles(user, "Sale")
		changes.append({"user": user, "role": "Sale"})

	frappe.db.commit()
	return {"changes": changes, "protected": sorted(protected), "missing": missing}


def verify() -> dict:
	rows = frappe.db.sql(
		"""
		SELECT u.name AS user, GROUP_CONCAT(hr.role ORDER BY hr.role SEPARATOR ' | ') AS roles
		FROM `tabUser` u
		LEFT JOIN `tabHas Role` hr ON hr.parent=u.name AND hr.parenttype='User'
		WHERE u.enabled=1 AND u.user_type='System User'
		GROUP BY u.name ORDER BY u.name
		""",
		as_dict=True,
	)
	return {"users": rows, "protected": sorted(PROTECTED_USERS), "missing": [e for e in ROLE_BY_EMAIL if not frappe.db.exists("User", e)]}
