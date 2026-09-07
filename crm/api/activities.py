import json

import frappe
from bs4 import BeautifulSoup
from frappe import _
from frappe.desk.form.load import get_docinfo
from frappe.query_builder import JoinType
from frappe.translate import get_translated_doctypes

from crm.fcrm.doctype.call_log.call_log import parse_call_log


IGNORED_VERSION_FIELDS = {
	"docstatus",
	"idx",
	"modified",
	"modified_by",
	"owner",
	"naming_series",
	"response_by",
	"sla_creation",
	"sla",
	"first_response_time",
	"last_response_time",
	"first_responded_on",
	"last_responded_on",
	"rolling_responses",
}


@frappe.whitelist()
def get_activities(doctype: str, name: str):
	if not doctype or not name or not frappe.db.exists(doctype, name):
		frappe.throw(_("Document not found"), frappe.DoesNotExistError)

	if not frappe.has_permission(doctype, "read", name):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	return get_document_activities(doctype, name)


def get_document_activities(doctype: str, name: str):
	get_docinfo("", doctype, name)
	docinfo = frappe.response["docinfo"]
	meta = frappe.get_meta(doctype)
	fields = {field.fieldname: {"label": field.label, "options": field.options} for field in meta.fields}

	doc = frappe.db.get_values(doctype, name, ["creation", "owner"])[0]
	activities = [
		{
			"activity_type": "creation",
			"creation": doc[0],
			"owner": doc[1],
			"data": _("created this document"),
			"is_lead": False,
		}
	]

	docinfo.versions.reverse()

	for version in docinfo.versions:
		data = json.loads(version.data)
		if not data.get("changed"):
			continue

		if change := data.get("changed")[0]:
			field = fields.get(change[0])

			if not field or change[0] in IGNORED_VERSION_FIELDS or (not change[1] and not change[2]):
				continue

			field_label = field.get("label") or change[0]
			field_option = field.get("options") or None

			activity_type = "changed"
			data = {
				"field": change[0],
				"field_label": field_label,
				"old_value": change[1],
				"value": change[2],
			}

			if not change[1] and change[2]:
				activity_type = "added"
				data = {
					"field": change[0],
					"field_label": field_label,
					"value": change[2],
				}
			elif change[1] and not change[2]:
				activity_type = "removed"
				data = {
					"field": change[0],
					"field_label": field_label,
					"value": change[1],
				}

			if data.get("value") and field_option and is_translatable(field_option):
				data["value"] = _(data["value"])

				if data.get("old_value"):
					data["old_value"] = _(data["old_value"])

		activities.append(
			{
				"activity_type": activity_type,
				"creation": version.creation,
				"owner": version.owner,
				"data": data,
				"is_lead": False,
				"options": field_option,
			}
		)

	for comment in docinfo.comments:
		activities.append(
			{
				"name": comment.name,
				"activity_type": "comment",
				"creation": comment.creation,
				"owner": comment.owner,
				"content": comment.content,
				"attachments": get_attachments("Comment", comment.name),
				"is_lead": False,
			}
		)

	for communication in docinfo.communications + docinfo.automated_messages:
		activities.append(
			{
				"activity_type": "communication",
				"communication_type": communication.communication_type,
				"communication_date": communication.communication_date or communication.creation,
				"creation": communication.creation,
				"data": {
					"subject": communication.subject,
					"content": communication.content,
					"sender_full_name": communication.sender_full_name,
					"sender": communication.sender,
					"recipients": communication.recipients,
					"cc": communication.cc,
					"bcc": communication.bcc,
					"attachments": get_attachments("Communication", communication.name),
					"read_by_recipient": communication.read_by_recipient,
					"delivery_status": communication.delivery_status,
				},
				"is_lead": False,
			}
		)

	for attachment_log in docinfo.attachment_logs:
		activities.append(
			{
				"name": attachment_log.name,
				"activity_type": "attachment_log",
				"creation": attachment_log.creation,
				"owner": attachment_log.owner,
				"data": parse_attachment_log(attachment_log.content, attachment_log.comment_type),
				"is_lead": False,
			}
		)

	linked_calls = get_linked_calls(doctype, name)
	calls = linked_calls.get("calls", [])
	notes = get_linked_notes(doctype, name) + linked_calls.get("notes", [])
	# Admissions work items are canonical CRM Actions. Generic Task remains
	# available to ordinary CRM records, but must not leak into Student/Contact
	# admissions detail activity payloads.
	tasks = [] if doctype in {"CRM Lead", "CRM Student"} else get_linked_tasks(doctype, name) + linked_calls.get("tasks", [])
	attachments = get_attachments(doctype, name)

	activities.sort(key=lambda x: x["creation"], reverse=True)
	activities = handle_multiple_versions(activities)

	return activities, calls, notes, tasks, attachments


def get_attachments(doctype: str, name: str):
	return (
		frappe.db.get_all(
			"File",
			filters={"attached_to_doctype": doctype, "attached_to_name": name},
			fields=[
				"name",
				"file_name",
				"file_type",
				"file_url",
				"file_size",
				"is_private",
				"modified",
				"creation",
				"owner",
			],
		)
		or []
	)


def handle_multiple_versions(versions: list):
	activities = []
	grouped_versions = []
	old_version = None
	for version in versions:
		is_version = version["activity_type"] in ["changed", "added", "removed"]
		if not is_version:
			activities.append(version)
		if not old_version:
			old_version = version
			if is_version:
				grouped_versions.append(version)
			continue
		if is_version and old_version.get("owner") and version["owner"] == old_version["owner"]:
			grouped_versions.append(version)
		else:
			if grouped_versions:
				activities.append(parse_grouped_versions(grouped_versions))
			grouped_versions = []
			if is_version:
				grouped_versions.append(version)
		old_version = version
		if version == versions[-1] and grouped_versions:
			activities.append(parse_grouped_versions(grouped_versions))

	return activities


def parse_grouped_versions(versions: list):
	version = versions[0]
	if len(versions) == 1:
		return version
	other_versions = versions[1:]
	version["other_versions"] = other_versions
	return version


def get_linked_calls(doctype: str, name: str):
	calls = frappe.db.get_all(
		"Call Log",
		filters={"reference_doctype": doctype, "reference_docname": name},
		fields=[
			"name",
			"caller",
			"receiver",
			"from",
			"to",
			"duration",
			"start_time",
			"end_time",
			"status",
			"type",
			"recording_url",
			"creation",
			"note",
		],
	)

	linked_calls = frappe.db.get_all(
		"Dynamic Link",
		filters={
			"link_doctype": doctype,
			"link_name": name,
			"parenttype": "Call Log",
		},
		pluck="parent",
	)

	notes = []
	tasks = []

	if linked_calls:
		CallLog = frappe.qb.DocType("Call Log")
		Link = frappe.qb.DocType("Dynamic Link")
		query = (
			frappe.qb.from_(CallLog)
			.select(
				CallLog.name,
				CallLog.caller,
				CallLog.receiver,
				CallLog["from"],
				CallLog.to,
				CallLog.duration,
				CallLog.start_time,
				CallLog.end_time,
				CallLog.status,
				CallLog.type,
				CallLog.recording_url,
				CallLog.creation,
				CallLog.note,
				Link.link_doctype,
				Link.link_name,
			)
			.join(Link, JoinType.inner)
			.on(Link.parent == CallLog.name)
			.where(CallLog.name.isin(linked_calls))
		)
		_calls = query.run(as_dict=True)

		for call in _calls:
			if call.get("link_doctype") == "FCRM Note":
				notes.append(call.link_name)
			elif call.get("link_doctype") == "Task" and doctype not in {"CRM Lead", "CRM Student"}:
				tasks.append(call.link_name)

		_calls = [call for call in _calls if call.get("link_doctype") not in ["FCRM Note", "Task"]]
		if _calls:
			calls = calls + _calls

	if notes:
		notes = frappe.db.get_all(
			"FCRM Note",
			filters={"name": ("in", notes)},
			fields=["name", "content", "owner", "modified"],
		)
		for note in notes:
			note["owner_full_name"] = frappe.get_cached_value("User", note.owner, "full_name")

	if tasks:
		tasks = frappe.db.get_all(
			"Task",
			filters={"name": ("in", tasks)},
			fields=[
				"name",
				"title",
				"description",
				"assigned_to",
				"due_date",
				"priority",
				"status",
				"modified",
			],
		)

	calls = [parse_call_log(call) for call in calls] if calls else []

	return {"calls": calls, "notes": notes, "tasks": tasks}


def get_linked_notes(doctype: str, name: str):
	notes = frappe.db.get_all(
		"FCRM Note",
		filters={"reference_doctype": doctype, "reference_docname": name},
		fields=["name", "content", "owner", "modified", "creation"],
	)
	for note in notes:
		note["owner_full_name"] = frappe.get_cached_value("User", note.owner, "full_name")
	return notes or []


def get_linked_tasks(doctype: str, name: str):
	return (
		frappe.db.get_all(
			"Task",
			filters={"reference_doctype": doctype, "reference_docname": name},
			fields=[
				"name",
				"title",
				"description",
				"assigned_to",
				"due_date",
				"priority",
				"status",
				"modified",
				"creation",
			],
		)
		or []
	)


def parse_attachment_log(html: str, type: str):
	soup = BeautifulSoup(html, "html.parser")
	a_tag = soup.find("a")
	type = "added" if type == "Attachment" else "removed"
	if not a_tag:
		return {
			"type": type,
			"file_name": html.replace("Removed ", ""),
			"file_url": "",
			"is_private": False,
		}

	is_private = False
	if "private/files" in a_tag["href"]:
		is_private = True

	return {
		"type": type,
		"file_name": a_tag.text,
		"file_url": a_tag["href"],
		"is_private": is_private,
	}


def is_translatable(doctype: str) -> bool:
	return doctype in get_translated_doctypes()
