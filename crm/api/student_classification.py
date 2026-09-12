"""Admin Need/Tag catalogues and permission-scoped Student assignments."""

import frappe

from crm.fcrm.controlled_catalog import GROUP_DOCTYPES, normalize_group_code, require_admin
from crm.fcrm.segment_rules import fail, integer
from crm.fcrm.student_segments import locked, payload

CATALOG = {
	"need": {"doctype": "CRM Need", "field": "needs", "link": "need", "label": "Need"},
	"tag": {"doctype": "CRM Tag", "field": "tags", "link": "tag", "label": "Tag"},
}
TERM_FIELDS = {"code", "label", "group_name", "description"}
GROUP_FIELDS = {"code", "label", "description", "sort_order"}


def _config(kind):
	if kind not in CATALOG:
		fail("kind must be need or tag.")
	return CATALOG[kind]


def _group_config(kind):
	if kind not in CATALOG:
		fail("kind must be need or tag.")
	return {"doctype": GROUP_DOCTYPES[kind], "term_doctype": CATALOG[kind]["doctype"]}


def _ensure_group(kind, group_name):
	group_name = str(group_name or "").strip()
	if not group_name:
		fail("group_name is required.")
	config = _group_config(kind)
	group_code = normalize_group_code(group_name)
	if not frappe.db.exists(config["doctype"], group_code):
		frappe.get_doc(
			{
				"doctype": config["doctype"],
				"code": group_code,
				"label": group_name,
				"status": "draft",
			}
		).insert()
	return group_code


def _term_data(kind, data):
	values = payload(data, TERM_FIELDS | {"group"})
	group = values.get("group")
	group_name = values.get("group_name")
	if group:
		if not frappe.db.exists(_group_config(kind)["doctype"], group):
			fail(f"Unknown {kind} group.")
		values["group_name"] = group_name or group
	else:
		values["group"] = _ensure_group(kind, group_name)
		values["group_name"] = str(group_name).strip()
	return values


def _create(kind, data):
	require_admin()
	config = _config(kind)
	return (
		frappe.get_doc({"doctype": config["doctype"], "status": "draft", **_term_data(kind, data)})
		.insert()
		.as_dict()
	)


def _update(kind, name, data, expected_revision):
	require_admin()
	config = _config(kind)
	doc = locked(config["doctype"], name, expected_revision)
	values = payload(data, (TERM_FIELDS | {"group"}) - {"code"})
	if "group" in values or "group_name" in values:
		values = _term_data(kind, values)
	doc.update(values)
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


def _list(kind, status="active", start=0, page_length=50, group=None):
	config = _config(kind)
	filters = {"status": status} if status else {}
	if group:
		filters["group"] = group
	rows = frappe.get_list(
		config["doctype"],
		filters=filters,
		fields=["name", "code", "label", "group", "group_name", "description", "status", "revision"],
		order_by="`group` asc, code asc",
		limit_start=integer(start, "start"),
		limit_page_length=integer(page_length, "page_length", maximum=100) or 50,
	)
	return _with_group_metadata(kind, rows)


def _with_group_metadata(kind, rows):
	config = _group_config(kind)
	group_names = {row.get("group") for row in rows if row.get("group")}
	groups = {}
	if group_names:
		groups = {
			group.name: group
			for group in frappe.get_all(
				config["doctype"],
				filters={"name": ["in", list(group_names)]},
				fields=["name", "code", "label"],
			)
		}
	for row in rows:
		group_code = row.get("group") or row.get("group_name")
		group = groups.get(group_code)
		row["group"] = group_code
		row["group_name"] = row.get("group_name") or group_code
		row["group_label"] = group.label if group else row["group_name"]
	return rows


def _create_group(kind, data):
	require_admin()
	config = _group_config(kind)
	return (
		frappe.get_doc({"doctype": config["doctype"], "status": "draft", **payload(data, GROUP_FIELDS)})
		.insert()
		.as_dict()
	)


def _update_group(kind, name, data, expected_revision):
	require_admin()
	config = _group_config(kind)
	doc = locked(config["doctype"], name, expected_revision)
	doc.update(payload(data, GROUP_FIELDS - {"code"}))
	return doc.save(ignore_version=False).as_dict()


def _transition_group(kind, name, status, expected_revision):
	require_admin()
	config = _group_config(kind)
	doc = locked(config["doctype"], name, expected_revision)
	doc.status = status
	return doc.save(ignore_version=False).as_dict()


def _delete_group(kind, name, expected_revision):
	require_admin()
	config = _group_config(kind)
	locked(config["doctype"], name, expected_revision)
	frappe.delete_doc(config["doctype"], name)
	return {"name": name, "deleted": True}


def _list_groups(kind, status="active", start=0, page_length=100):
	config = _group_config(kind)
	filters = {"status": status} if status else {}
	return frappe.get_list(
		config["doctype"],
		filters=filters,
		fields=["name", "code", "label", "description", "status", "sort_order", "revision"],
		order_by="sort_order asc, code asc",
		limit_start=integer(start, "start"),
		limit_page_length=integer(page_length, "page_length", maximum=100) or 100,
	)


def _paged_catalog(kind, *, groups, status="active", start=0, page_length=50, group=None):
	config = _group_config(kind) if groups else _config(kind)
	filters = {"status": status} if status else {}
	if group and not groups:
		filters["group"] = group
	rows = (
		_list_groups(kind, status, start, page_length)
		if groups
		else _list(kind, status, start, page_length, group)
	)
	count_rows = frappe.get_list(
		config["doctype"],
		filters=filters,
		fields=["count(name) as total"],
		limit_page_length=0,
	)
	return {
		"groups" if groups else CATALOG[kind]["field"]: rows,
		"total": int((count_rows[0].get("total") if count_rows else 0) or 0),
		"start": integer(start, "start"),
		"page_length": integer(page_length, "page_length", maximum=100) or (100 if groups else 50),
	}


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
def create_need_group(data):
	return _create_group("need", data)


@frappe.whitelist()
def update_need_group(name, data, expected_revision):
	return _update_group("need", name, data, expected_revision)


@frappe.whitelist()
def transition_need_group(name, status, expected_revision):
	return _transition_group("need", name, status, expected_revision)


@frappe.whitelist()
def delete_need_group(name, expected_revision):
	return _delete_group("need", name, expected_revision)


@frappe.whitelist()
def list_need_groups(status="active", start=0, page_length=100):
	return _list_groups("need", status, start, page_length)


@frappe.whitelist()
def list_need_groups_page(status="active", start=0, page_length=20):
	return _paged_catalog("need", groups=True, status=status, start=start, page_length=page_length)


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
def list_needs_page(status="active", group=None, start=0, page_length=20):
	return _paged_catalog(
		"need", groups=False, status=status, group=group, start=start, page_length=page_length
	)


@frappe.whitelist()
def list_tags_page(status="active", group=None, start=0, page_length=20):
	return _paged_catalog(
		"tag", groups=False, status=status, group=group, start=start, page_length=page_length
	)


@frappe.whitelist()
def create_tag_group(data):
	return _create_group("tag", data)


@frappe.whitelist()
def update_tag_group(name, data, expected_revision):
	return _update_group("tag", name, data, expected_revision)


@frappe.whitelist()
def transition_tag_group(name, status, expected_revision):
	return _transition_group("tag", name, status, expected_revision)


@frappe.whitelist()
def delete_tag_group(name, expected_revision):
	return _delete_group("tag", name, expected_revision)


@frappe.whitelist()
def list_tag_group_definitions(status="active", start=0, page_length=100):
	return _list_groups("tag", status, start, page_length)


@frappe.whitelist()
def list_tag_groups_page(status="active", start=0, page_length=20):
	return _paged_catalog("tag", groups=True, status=status, start=start, page_length=page_length)


@frappe.whitelist()
def list_tag_groups(status="active", start=0, page_length=100):
	"""Return active Tag records grouped by their catalogue group."""
	tags = _list("tag", status, start, page_length)
	groups = {}
	for tag in tags:
		group_name = tag.get("group_name") or "Khác"
		group = groups.setdefault(
			group_name,
			{"group_name": group_name, "group_label": tag.get("group_label") or group_name, "tags": []},
		)
		group["tags"].append(tag)
	return list(groups.values())


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


def _load_student_for_write(student, expected_modified):
	doc = frappe.get_doc("CRM Student", student, for_update=True)
	doc.check_permission("write")
	if str(doc.modified) != str(expected_modified):
		fail("Student changed; reload before retrying.", "REVISION_CONFLICT")
	return doc


def _validate_tag_name(value, *, active=False):
	if not isinstance(value, str) or not value.strip():
		fail("Tag identifier must be a non-empty string.")
	tag = value.strip()
	if not frappe.db.exists("CRM Tag", tag):
		fail("Unknown tag identifier.")
	if active and frappe.db.get_value("CRM Tag", tag, "status") != "active":
		fail("Only active tags can be assigned to Students.")
	return tag


def _student_tag_names(doc):
	return [row.tag for row in doc.get("tags", [])]


def _replace_student_tags(doc, tag_names):
	doc.set("tags", [])
	for tag in tag_names:
		doc.append("tags", {"tag": tag})
	doc.save(ignore_version=False)
	return _result(doc)


@frappe.whitelist()
def add_student_tag(student, tag, expected_modified):
	doc = _load_student_for_write(student, expected_modified)
	tag = _validate_tag_name(tag, active=True)
	tag_names = _student_tag_names(doc)
	if tag not in tag_names:
		doc.append("tags", {"tag": tag})
		doc.save(ignore_version=False)
	return _result(doc)


@frappe.whitelist()
def remove_student_tag(student, tag, expected_modified):
	doc = _load_student_for_write(student, expected_modified)
	tag = _validate_tag_name(tag)
	tag_names = _student_tag_names(doc)
	if tag not in tag_names:
		return _result(doc)
	return _replace_student_tags(doc, [value for value in tag_names if value != tag])


@frappe.whitelist()
def update_student_tag(student, tag, new_tag, expected_modified):
	doc = _load_student_for_write(student, expected_modified)
	tag = _validate_tag_name(tag)
	new_tag = _validate_tag_name(new_tag, active=True)
	tag_names = _student_tag_names(doc)
	if tag not in tag_names:
		fail("The Student does not have this tag assigned.")
	if tag == new_tag:
		return _result(doc)
	if new_tag in tag_names:
		fail("The Student already has the replacement tag assigned.")
	return _replace_student_tags(
		doc,
		[new_tag if value == tag else value for value in tag_names],
	)


@frappe.whitelist()
def update_classifications(student, data, expected_modified):
	doc = _load_student_for_write(student, expected_modified)
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
		"admission_stage": doc.student_stage,
		"potential": doc.potential,
		"intent": doc.intent,
		"needs": [_assignment(row, "need") for row in doc.get("needs", [])],
		"tags": [_assignment(row, "tag") for row in doc.get("tags", [])],
	}


def _assignment(row, link):
	result = row.as_dict()
	result["term"] = getattr(row, link)
	return result
