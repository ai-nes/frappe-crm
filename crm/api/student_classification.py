"""Admin Need/Tag catalogues and permission-scoped Student assignments."""

import frappe

from crm.fcrm.controlled_catalog import require_admin
from crm.fcrm.segment_rules import fail, integer
from crm.fcrm.student_segments import locked, payload

CATALOG = {
	"need": {"doctype": "CRM Need", "field": "needs", "link": "need", "label": "Need"},
	"tag": {"doctype": "CRM Tag", "field": "tags", "link": "tag", "label": "Tag"},
}
TERM_FIELDS = {"code", "label", "group_name", "description"}


def _config(kind):
	if kind not in CATALOG:
		fail("kind must be need or tag.")
	return CATALOG[kind]


def _create(kind, data):
	require_admin()
	config = _config(kind)
	return (
		frappe.get_doc({"doctype": config["doctype"], "status": "draft", **payload(data, TERM_FIELDS)})
		.insert()
		.as_dict()
	)


def _update(kind, name, data, expected_revision):
	require_admin()
	config = _config(kind)
	doc = locked(config["doctype"], name, expected_revision)
	doc.update(payload(data, TERM_FIELDS - {"code"}))
	return doc.save(ignore_version=False).as_dict()


def _transition(kind, name, status, expected_revision):
	require_admin()
	config = _config(kind)
	doc = locked(config["doctype"], name, expected_revision)
	doc.status = status
	return doc.save(ignore_version=False).as_dict()


def _delete(kind, name, expected_revision):
	require_admin()
	config = _config(kind)
	locked(config["doctype"], name, expected_revision)
	frappe.delete_doc(config["doctype"], name)
	return {"name": name, "deleted": True}


def _list(kind, status="active", start=0, page_length=50):
	config = _config(kind)
	filters = {"status": status} if status else {}
	return frappe.get_list(
		config["doctype"],
		filters=filters,
		fields=["name", "code", "label", "group_name", "description", "status", "revision"],
		order_by="group_name asc, code asc",
		limit_start=integer(start, "start"),
		limit_page_length=integer(page_length, "page_length", maximum=100) or 50,
	)


@frappe.whitelist()
def create_need(data):
	return _create("need", data)


@frappe.whitelist()
def update_need(name, data, expected_revision):
	return _update("need", name, data, expected_revision)


@frappe.whitelist()
def transition_need(name, status, expected_revision):
	return _transition("need", name, status, expected_revision)


@frappe.whitelist()
def delete_need(name, expected_revision):
	return _delete("need", name, expected_revision)


@frappe.whitelist()
def list_needs(status="active", start=0, page_length=50):
	return _list("need", status, start, page_length)


@frappe.whitelist()
def create_tag(data):
	return _create("tag", data)


@frappe.whitelist()
def update_tag(name, data, expected_revision):
	return _update("tag", name, data, expected_revision)


@frappe.whitelist()
def transition_tag(name, status, expected_revision):
	return _transition("tag", name, status, expected_revision)


@frappe.whitelist()
def delete_tag(name, expected_revision):
	return _delete("tag", name, expected_revision)


@frappe.whitelist()
def list_tags(status="active", start=0, page_length=50):
	return _list("tag", status, start, page_length)


@frappe.whitelist()
def create_term(data):
	"""Compatibility wrapper; new clients must call create_need/create_tag."""
	data = payload(data, TERM_FIELDS | {"kind"})
	kind = data.pop("kind", None)
	return _create(kind, data)


@frappe.whitelist()
def update_term(name, data, expected_revision):
	"""Compatibility wrapper resolved by the existing catalogue record."""
	record = frappe.db.get_value("CRM Need", name, "name")
	return _update("need" if record else "tag", name, data, expected_revision)


@frappe.whitelist()
def transition_term(name, status, expected_revision):
	record = frappe.db.get_value("CRM Need", name, "name")
	return _transition("need" if record else "tag", name, status, expected_revision)


@frappe.whitelist()
def delete_term(name, expected_revision):
	record = frappe.db.get_value("CRM Need", name, "name")
	return _delete("need" if record else "tag", name, expected_revision)


@frappe.whitelist()
def list_terms(kind=None, status="active", start=0, page_length=50):
	if kind:
		return _list(kind, status, start, page_length)
	return _list("need", status, start, page_length) + _list("tag", status, start, page_length)


@frappe.whitelist()
def get_classifications(student):
	doc = frappe.get_doc("CRM Student", student)
	doc.check_permission("read")
	return _result(doc)


@frappe.whitelist()
def update_classifications(student, data, expected_modified):
	doc = frappe.get_doc("CRM Student", student, for_update=True)
	doc.check_permission("write")
	if str(doc.modified) != str(expected_modified):
		fail("Student changed; reload before retrying.", "REVISION_CONFLICT")
	data = payload(data, {"potential", "intent", "needs", "tags"})
	for field in ("potential", "intent"):
		if field in data:
			doc.set(field, data[field])
	for kind in ("need", "tag"):
		config = _config(kind)
		if config["field"] not in data:
			continue
		values = data[config["field"]]
		if not isinstance(values, list) or len(values) > 100 or any(not isinstance(v, str) for v in values):
			fail(f"{config['field']} must be a list of at most 100 term identifiers.")
		if len(set(values)) != len(values):
			fail("Duplicate classifications are not allowed.")
		for value in values:
			if not frappe.db.exists(config["doctype"], value):
				fail(f"Unknown {kind} identifier.")
		doc.set(config["field"], [])
		for value in values:
			doc.append(config["field"], {config["link"]: value})
	doc.save(ignore_version=False)
	return _result(doc)


def _result(doc):
	return {
		"student": doc.name,
		"modified": str(doc.modified),
		"admission_stage": doc.enrollment_status,
		"potential": doc.potential,
		"intent": doc.intent,
		"needs": [_assignment(row, "need") for row in doc.get("needs", [])],
		"tags": [_assignment(row, "tag") for row in doc.get("tags", [])],
	}


def _assignment(row, link):
	result = row.as_dict()
	result["term"] = getattr(row, link)
	return result
