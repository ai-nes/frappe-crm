"""Upgrade saved segments without activating or discarding existing audiences."""

import frappe


def execute():
	# Existing rows have no business owner metadata. Treat them as inactive until
	# an owner reviews the purpose and rules; never infer active from old usage.
	frappe.db.sql("""
		UPDATE `tabCRM Segment`
		SET status = 'inactive', segment_type = 'dynamic', revision = 0,
			responsible_user = owner
		WHERE IFNULL(responsible_user, '') = ''
	""")
	frappe.db.add_index("CRM Segment", ["status", "segment_type"])
	frappe.db.add_unique("CRM Segment Member", ["segment", "student"])
	frappe.db.add_index("CRM Segment Member", ["student", "segment"])
	frappe.db.add_index("CRM Student Need Assignment", ["need", "parent"])
	frappe.db.add_index("CRM Student Tag Assignment", ["tag", "parent"])
	frappe.db.add_index("CRM Need", ["status", "group"])
	frappe.db.add_index("CRM Tag", ["status", "group"])
	from crm.fcrm.classification_catalog import seed_catalog

	seed_catalog()
	_migrate_legacy_classifications()


def _migrate_legacy_classifications():
	"""Copy the superseded shared dictionary into separate Need/Tag records."""
	if not frappe.db.exists("DocType", "CRM Classification Term"):
		return
	term_map = {}
	for term in frappe.get_all(
		"CRM Classification Term",
		fields=["name", "code", "label", "kind", "group_name", "description", "status", "revision"],
	):
		doctype = "CRM Need" if term.kind == "need" else "CRM Tag"
		if not frappe.db.exists(doctype, {"code": term.code}):
			from crm.patches.v1_0.migrate_classification_groups import ensure_group_for_value

			group_code = ensure_group_for_value(term.kind, term.group_name)
			new_term = frappe.get_doc(
				{
					"doctype": doctype,
					"code": term.code,
					"label": term.label,
					"group": group_code,
					"group_name": term.group_name,
					"description": term.description,
					"status": term.status,
					"revision": term.revision or 0,
				}
			).insert(ignore_permissions=True)
		else:
			new_name = frappe.db.get_value(doctype, {"code": term.code}, "name")
			new_term = frappe.get_doc(doctype, new_name)
		term_map[term.name] = new_term.name

	for row in frappe.get_all(
		"CRM Student Classification",
		fields=["parent", "term", "assigned_by", "assigned_at", "source", "idx"],
	):
		new_name = term_map.get(row.term)
		if not new_name or not frappe.db.exists("CRM Student", row.parent):
			continue
		old_term = frappe.db.get_value("CRM Classification Term", row.term, ["kind"], as_dict=True)
		kind = old_term.kind
		assignment_doctype = "CRM Student Need Assignment" if kind == "need" else "CRM Student Tag Assignment"
		assignment_field = "need" if kind == "need" else "tag"
		parentfield = "needs" if kind == "need" else "tags"
		if frappe.db.exists(assignment_doctype, {"parent": row.parent, assignment_field: new_name}):
			continue
		name = frappe.generate_hash(length=10)
		frappe.db.sql(
			f"""INSERT INTO `tab{assignment_doctype}`
			(name, creation, modified, modified_by, owner, docstatus, idx, `{assignment_field}`,
			 parent, parentfield, parenttype, assigned_by, assigned_at, source)
			VALUES (%s, NOW(), NOW(), %s, %s, 0, %s, %s, %s, %s, 'CRM Student', %s, %s, %s)""",
			(
				name,
				frappe.session.user,
				frappe.session.user,
				row.idx or 1,
				new_name,
				row.parent,
				parentfield,
				row.assigned_by,
				row.assigned_at,
				row.source or "legacy",
			),
		)
