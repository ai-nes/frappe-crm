"""One test login per canonical CRM role.

Simple, idempotent: a `System User` per role in the canonical policy, each with
exactly its own profile assigned through the canonical authority and a shared
local password. For local demo / QA only.
"""

from __future__ import annotations

import frappe

from crm.api.user import set_canonical_crm_profile

# (role, email, full name). Roles are the canonical CANONICAL_SELECTABLE_ROLES.
ROLE_ACCOUNTS = (
	("Admissions Director", "admin@gmail.com", "Giám đốc Tuyển sinh"),
	("System Manager", "system@gmail.com", "Quản trị Hệ thống"),
	("Sale", "sale@gmail.com", "Nhân viên Tư vấn"),
	("Lead Sales", "leadsales@gmail.com", "Trưởng nhóm Tư vấn"),
	("Marketing", "marketing@gmail.com", "Nhân viên Marketing"),
	("Promoter", "promoter@gmail.com", "Promoter Thực địa"),
)
PASSWORD = "12345@"


def execute() -> dict:
	from frappe.utils.password import update_password

	created, updated = [], []
	for role, email, full_name in ROLE_ACCOUNTS:
		first, _, last = full_name.partition(" ")
		if frappe.db.exists("User", email):
			user = frappe.get_doc("User", email)
			updated.append(email)
		else:
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": first,
					"last_name": last or None,
					"user_type": "System User",
					"enabled": 1,
					"language": "vi",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
			created.append(email)

		user.enabled = 1
		set_canonical_crm_profile(user, role)
		user.flags.ignore_permissions = True
		user.save(ignore_permissions=True)
		# Bypass the strength policy for these throwaway local logins.
		update_password(user=email, pwd=PASSWORD, logout_all_sessions=True)

	frappe.db.commit()
	return {
		"password": PASSWORD,
		"created": created,
		"updated": updated,
		"accounts": [{"role": r, "email": e} for r, e, _ in ROLE_ACCOUNTS],
	}
