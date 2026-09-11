"""APIs for uploading documents to a Student admission profile."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils.file_manager import check_max_file_size

from crm.fcrm.student_profile import allowed_document_types, refresh_document_completeness
from crm.fcrm.student_reference import canonical_student


def _required_text(value: str | None, fieldname: str) -> str:
	value = str(value or "").strip()
	if not value:
		frappe.throw(_("{0} is required.").format(fieldname), frappe.ValidationError)
	return value


def _uploaded_content() -> tuple[str, bytes]:
	files = getattr(frappe.request, "files", None)
	uploaded = files.get("file") if files else None
	if not uploaded:
		frappe.throw(_("A file is required."), frappe.ValidationError)

	filename = str(getattr(uploaded, "filename", "") or "").strip()
	if not filename:
		frappe.throw(_("The uploaded file must have a filename."), frappe.ValidationError)

	content = uploaded.stream.read()
	if not content:
		frappe.throw(_("The uploaded file is empty."), frappe.ValidationError)
	check_max_file_size(content)
	return filename, content


def _next_document_version(profile: str, document_type: str) -> int:
	rows = frappe.get_all(
		"CRM Student Document",
		filters={
			"student_admission_profile": profile,
			"document_type": document_type,
		},
		fields=["version"],
		order_by="version desc",
		limit_page_length=1,
		ignore_permissions=True,
	)
	return int(rows[0].version or 0) + 1 if rows else 1


def _document_response(document) -> dict[str, Any]:
	return {
		"id": document.name,
		"student": document.student,
		"profile": document.student_admission_profile,
		"documentType": document.document_type,
		"application": document.application,
		"file": document.file,
		"isPrivate": bool(document.is_private),
		"status": document.status,
		"version": int(document.version or 1),
		"sourceReference": document.source_reference,
	}


@frappe.whitelist(methods=["POST"])
def upload_document(
	student: str,
	profile: str,
	document_type: str,
	application: str | None = None,
) -> dict[str, Any]:
	"""Upload one private file and register it on a Student admission profile."""
	student_reference = _required_text(student, "student")
	profile_name = _required_text(profile, "profile")
	document_type_name = _required_text(document_type, "document_type")
	student_name = canonical_student(student_reference) or student_reference
	if not frappe.db.exists("CRM Student", student_name):
		frappe.throw(_("Student does not exist."), frappe.DoesNotExistError)

	student_doc = frappe.get_doc("CRM Student", student_name)
	student_doc.check_permission("read")
	profile_doc = frappe.get_doc("CRM Student Admission Profile", profile_name)
	if profile_doc.student != student_name:
		frappe.throw(
			_("Student Admission Profile does not belong to this Student."),
			frappe.ValidationError,
		)
	if application and application != profile_doc.application:
		frappe.throw(
			_("Admission Application does not belong to this Student Admission Profile."),
			frappe.ValidationError,
		)
	if document_type_name not in allowed_document_types(profile_doc):
		frappe.throw(
			_("Document Type is not allowed by the selected Student profile."),
			frappe.ValidationError,
		)

	filename, content = _uploaded_content()
	version = _next_document_version(profile_doc.name, document_type_name)
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": filename,
			"content": content,
			"folder": "Home",
			"is_private": 1,
			"attached_to_doctype": "CRM Student Admission Profile",
			"attached_to_name": profile_doc.name,
		}
	)
	file_doc.flags.ignore_permissions = True
	file_doc.insert()

	try:
		document = frappe.get_doc(
			{
				"doctype": "CRM Student Document",
				"student": student_name,
				"student_admission_profile": profile_doc.name,
				"document_type": document_type_name,
				"application": profile_doc.application,
				"file": file_doc.file_url,
				"is_private": 1,
				"status": "Uploaded",
				"version": version,
				"source_reference": f"upload:{file_doc.name}",
			}
		)
		document.check_permission("create")
		document.insert()
	except Exception:
		if file_doc.name and frappe.db.exists("File", file_doc.name):
			frappe.delete_doc("File", file_doc.name, ignore_permissions=True, force=True)
		raise

	file_doc.db_set(
		{
			"attached_to_doctype": "CRM Student Document",
			"attached_to_name": document.name,
		},
		update_modified=False,
	)
	completeness = refresh_document_completeness(profile_doc.name)
	return {
		"document": _document_response(document),
		"file": {
			"id": file_doc.name,
			"fileName": file_doc.file_name,
			"fileUrl": file_doc.file_url,
			"isPrivate": True,
		},
		"documentCompleteness": completeness,
	}
