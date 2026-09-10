"""Migrate legacy classifications and remove their obsolete DocTypes."""

import frappe

from crm.patches.v1_0.migrate_classification_groups import ensure_group_for_value

LEGACY_TERM_DOCTYPE = "CRM Classification Term"
LEGACY_ASSIGNMENT_DOCTYPE = "CRM Student Classification"
TERM_CONFIG = {
	"need": {
		"doctype": "CRM Need",
		"assignment_doctype": "CRM Student Need Assignment",
		"assignment_field": "need",
		"parentfield": "needs",
	},
	"tag": {
		"doctype": "CRM Tag",
		"assignment_doctype": "CRM Student Tag Assignment",
		"assignment_field": "tag",
		"parentfield": "tags",
	},
}
VALID_STATUSES = {"draft", "active", "inactive", "archive"}


def _legacy_exists():
	return any(
		(
			frappe.db.exists("DocType", doctype),
			frappe.db.table_exists(doctype),
		)
		for doctype in (LEGACY_TERM_DOCTYPE, LEGACY_ASSIGNMENT_DOCTYPE)
	)


def _legacy_terms():
	if not frappe.db.table_exists(LEGACY_TERM_DOCTYPE):
		return []
	return frappe.db.sql(
		f"""
		SELECT name, code, label, kind, group_name, description, status, revision
		FROM `tab{LEGACY_TERM_DOCTYPE}`
		ORDER BY name
		""",
		as_dict=True,
	)


def _migrate_terms():
	term_map = {}
	for term in _legacy_terms():
		kind = term.kind
		config = TERM_CONFIG.get(kind)
		if not config:
			frappe.throw(
				f"Cannot migrate {LEGACY_TERM_DOCTYPE} {term.name}: unknown kind {kind!r}.",
				frappe.ValidationError,
			)
		status = term.status or "draft"
		if status not in VALID_STATUSES:
			frappe.throw(
				f"Cannot migrate {LEGACY_TERM_DOCTYPE} {term.name}: unknown status {status!r}.",
				frappe.ValidationError,
			)

		group = ensure_group_for_value(kind, term.group_name)
		new_name = frappe.db.get_value(config["doctype"], {"code": term.code}, "name")
		if not new_name:
			new_term = frappe.get_doc(
				{
					"doctype": config["doctype"],
					"code": term.code,
					"label": term.label,
					"group": group,
					"group_name": term.group_name,
					"description": term.description,
					"status": "draft",
					"revision": 0,
				}
			).insert(ignore_permissions=True)
			new_name = new_term.name

			# New catalogue validation requires draft on insert. Restore the
			# legacy lifecycle state only after the document exists.
			if status != "draft" or int(term.revision or 0):
				frappe.db.set_value(
					config["doctype"],
					new_name,
					{"status": status, "revision": int(term.revision or 0)},
					update_modified=False,
				)
		term_map[term.name] = (kind, new_name)
	return term_map


def _next_idx(doctype, parent):
	return (
		frappe.db.sql(
			f"SELECT COALESCE(MAX(idx), 0) + 1 FROM `tab{doctype}` WHERE parent = %s",
			(parent,),
		)[0][0]
		or 1
	)


def _migrate_assignments(term_map):
	if not frappe.db.table_exists(LEGACY_ASSIGNMENT_DOCTYPE):
		return
	if not term_map:
		if frappe.db.count(LEGACY_ASSIGNMENT_DOCTYPE):
			frappe.throw(
				f"{LEGACY_ASSIGNMENT_DOCTYPE} contains rows but no legacy terms are available.",
				frappe.ValidationError,
			)
		return

	rows = frappe.db.sql(
		f"""
		SELECT name, parent, term, assigned_by, assigned_at, source, idx,
			creation, modified, modified_by, owner
		FROM `tab{LEGACY_ASSIGNMENT_DOCTYPE}`
		ORDER BY parent, idx, name
		""",
		as_dict=True,
	)
	for row in rows:
		mapped = term_map.get(row.term)
		if not mapped:
			frappe.throw(
				f"Cannot migrate {LEGACY_ASSIGNMENT_DOCTYPE} {row.name}: term {row.term!r} is missing.",
				frappe.ValidationError,
			)
		if not frappe.db.exists("CRM Student", row.parent):
			frappe.throw(
				f"Cannot migrate {LEGACY_ASSIGNMENT_DOCTYPE} {row.name}: student {row.parent!r} is missing.",
				frappe.ValidationError,
			)

		kind, new_term = mapped
		config = TERM_CONFIG[kind]
		if frappe.db.exists(
			config["assignment_doctype"],
			{"parent": row.parent, config["assignment_field"]: new_term},
		):
			continue

		name = frappe.generate_hash(length=10)
		created_by = row.owner or row.assigned_by or frappe.session.user
		created_at = row.creation or row.assigned_at or frappe.utils.now_datetime()
		modified_at = row.modified or created_at
		modified_by = row.modified_by or created_by
		assigned_by = row.assigned_by or created_by
		assigned_at = row.assigned_at or created_at
		idx = _next_idx(config["assignment_doctype"], row.parent)
		frappe.db.sql(
			f"""
			INSERT INTO `tab{config["assignment_doctype"]}`
			(name, creation, modified, modified_by, owner, docstatus, idx,
			 `{config["assignment_field"]}`, parent, parentfield, parenttype,
			 assigned_by, assigned_at, source)
			VALUES (%s, %s, %s, %s, %s, 0, %s, %s, %s, %s, 'CRM Student', %s, %s, %s)
			""",
			(
				name,
				created_at,
				modified_at,
				modified_by,
				created_by,
				idx,
				new_term,
				row.parent,
				config["parentfield"],
				assigned_by,
				assigned_at,
				row.source or "legacy",
			),
		)


def _drop_legacy_doctype(doctype):
	if frappe.db.exists("DocType", doctype):
		frappe.delete_doc("DocType", doctype, force=True, ignore_permissions=True)
	frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{doctype}`")


def execute():
	if not _legacy_exists():
		return
	if not frappe.db.table_exists(LEGACY_TERM_DOCTYPE) and frappe.db.table_exists(LEGACY_ASSIGNMENT_DOCTYPE):
		frappe.throw(
			f"Cannot retire {LEGACY_ASSIGNMENT_DOCTYPE}: {LEGACY_TERM_DOCTYPE} table is missing.",
			frappe.ValidationError,
		)

	term_map = _migrate_terms()
	_migrate_assignments(term_map)
	_drop_legacy_doctype(LEGACY_ASSIGNMENT_DOCTYPE)
	_drop_legacy_doctype(LEGACY_TERM_DOCTYPE)
	frappe.clear_cache(doctype="CRM Student")
