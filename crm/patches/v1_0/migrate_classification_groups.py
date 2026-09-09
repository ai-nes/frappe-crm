"""Create Need/Tag group masters and backfill existing term links."""

import frappe

from crm.fcrm.classification_catalog import GROUP_CATALOG, seed_catalog
from crm.fcrm.controlled_catalog import normalize_group_code

GROUP_DOCTYPES = {
	"need": "CRM Need Group",
	"tag": "CRM Tag Group",
}
TERM_DOCTYPES = {
	"need": "CRM Need",
	"tag": "CRM Tag",
}


def ensure_group_for_value(kind, value):
	if kind not in GROUP_DOCTYPES:
		frappe.throw("kind must be need or tag.", frappe.ValidationError)
	legacy_name = str(value or "").strip()
	if not legacy_name:
		frappe.throw(f"{kind} group is required.", frappe.ValidationError)
	code = normalize_group_code(legacy_name)
	doctype = GROUP_DOCTYPES[kind]
	if not frappe.db.exists(doctype, code):
		frappe.get_doc(
			{
				"doctype": doctype,
				"code": code,
				"label": GROUP_CATALOG.get(kind, {}).get(code, legacy_name),
				"status": "draft",
			}
		).insert(ignore_permissions=True)
	else:
		group = frappe.get_doc(doctype, code)
		if code in GROUP_CATALOG.get(kind, {}) and group.label == code:
			frappe.db.set_value(doctype, code, "label", GROUP_CATALOG[kind][code], update_modified=False)
		if code in GROUP_CATALOG.get(kind, {}) and not group.sort_order:
			sort_order = list(GROUP_CATALOG[kind]).index(code) + 1
			frappe.db.set_value(doctype, code, "sort_order", sort_order * 10, update_modified=False)
	return code


def _migrate_term_groups(kind):
	term_doctype = TERM_DOCTYPES[kind]
	rows = frappe.db.sql(
		f"""
		SELECT name, `group`, group_name, status
		FROM `tab{term_doctype}`
		WHERE IFNULL(`group`, '') != '' OR IFNULL(group_name, '') != ''
		""",
		as_dict=True,
	)
	active_groups = set()
	for row in rows:
		legacy_name = row.group_name or row.group
		if not legacy_name:
			continue
		group_code = ensure_group_for_value(kind, legacy_name)
		updates = {}
		if row.group != group_code:
			updates["group"] = group_code
		if not row.group_name:
			updates["group_name"] = legacy_name
		if updates:
			frappe.db.set_value(term_doctype, row.name, updates, update_modified=False)
		if row.status == "active":
			active_groups.add(group_code)
	for group_code in active_groups:
		group_doctype = GROUP_DOCTYPES[kind]
		if frappe.db.get_value(group_doctype, group_code, "status") == "draft":
			frappe.db.set_value(
				group_doctype,
				group_code,
				{"status": "active", "revision": 1},
				update_modified=False,
			)


def execute():
	for kind in GROUP_DOCTYPES:
		_migrate_term_groups(kind)
	seed_catalog()
