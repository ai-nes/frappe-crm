from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.audit import get_lead_audit_logs, get_segment_audit_logs, get_student_audit_logs
from crm.api.student_school import create_student_with_lead
from crm.api.task import create_task
from crm.fcrm.lead_processing import update_processing_status
from crm.fcrm.student_stage import set_student_stage


class TestStudentAuditApi(FrappeTestCase):
	def setUp(self):
		self._original_user = frappe.session.user
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user(self._original_user)
		frappe.db.rollback()

	def test_student_audit_returns_creation_and_field_changes(self):
		student = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": "Audit API Student",
				"phone": "0912345678",
				"email": "audit-api-student@example.com",
			}
		).insert(ignore_permissions=True)

		student.full_name = "Updated Audit API Student"
		student.save(ignore_permissions=True, ignore_version=False)

		result = get_student_audit_logs(student.name)
		actions = [log["action"] for log in result["logs"]]
		updated = next(
			log for log in result["logs"] if log["action"] == "updated" and log["fieldname"] == "full_name"
		)

		self.assertGreaterEqual(result["total"], 2)
		self.assertIn("created", actions)
		self.assertEqual(updated["fieldname"], "full_name")
		self.assertEqual(updated["old_value"], "Audit API Student")
		self.assertEqual(updated["new_value"], "Updated Audit API Student")
		self.assertEqual(updated["owner"], "Administrator")
		self.assertEqual(
			updated["owner_full_name"], frappe.get_cached_value("User", "Administrator", "full_name")
		)

	def test_student_audit_returns_deleted_event_and_supports_pagination(self):
		student = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": "Deleted Audit API Student",
				"phone": "0912345679",
				"email": "deleted-audit-api-student@example.com",
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Deleted Document",
				"deleted_doctype": "CRM Student",
				"deleted_name": student.name,
				"data": "{}",
			}
		).insert(ignore_permissions=True)

		result = get_student_audit_logs(student.name, start=0, page_length=1)
		all_logs = get_student_audit_logs(student.name, page_length=100)

		self.assertEqual(len(result["logs"]), 1)
		self.assertGreaterEqual(result["total"], 2)
		self.assertTrue(any(log["action"] == "deleted" for log in all_logs["logs"]))
		self.assertTrue(all_logs["read_only"])

	def test_student_audit_includes_status_transition_metadata(self):
		student = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": "Audit Status Student",
				"phone": "0912345680",
				"student_stage": "New",
			}
		).insert(ignore_permissions=True)

		previous_flag = getattr(frappe.flags, "student_stage_service", False)
		frappe.flags.student_stage_service = True
		try:
			student.student_stage = "Attempting"
			student.save(ignore_permissions=True, ignore_version=False)
		finally:
			frappe.flags.student_stage_service = previous_flag

		result = get_student_audit_logs(student.name, page_length=100)
		status_log = next(
			log
			for log in result["logs"]
			if log.get("source") == "Version" and log.get("event_type") == "student_stage_changed"
		)

		self.assertEqual(status_log["category"], "status")
		self.assertEqual(status_log["fieldname"], "student_stage")
		self.assertEqual(status_log["old_value"], "New")
		self.assertEqual(status_log["new_value"], "Attempting")

	def test_student_stage_command_is_audited(self):
		student = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": "Audit Stage Command Student",
				"phone": "0912345691",
				"student_stage": "New",
			}
		).insert(ignore_permissions=True)

		baseline_revision = int(frappe.db.get_value("CRM Student", student.name, "student_context_revision") or 0)
		transition = set_student_stage(student.name, "Attempting")

		result = get_student_audit_logs(student.name, page_length=100)
		status_log = next(
			log
			for log in result["logs"]
			if log.get("source") == "Version"
			and log.get("event_type") == "student_stage_changed"
		)

		self.assertEqual(status_log["fieldname"], "student_stage")
		self.assertEqual(status_log["old_value"], "New")
		self.assertEqual(status_log["new_value"], "Attempting")
		current_revision = int(
			frappe.db.get_value("CRM Student", student.name, "student_context_revision") or 0
		)
		self.assertEqual(current_revision, baseline_revision + 1)
		self.assertEqual(transition["context_revision"], current_revision)

	def test_lead_processing_command_is_audited(self):
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"student_name": "Audit Processing Command Lead",
				"phone": "0912345692",
				"email": "audit-processing-command@example.com",
			}
		).insert(ignore_permissions=True)

		update_processing_status(lead.name, "PROCESSING", reason="Manual audit regression test")

		result = get_lead_audit_logs(lead.name, page_length=100)
		status_log = next(
			log
			for log in result["logs"]
			if log.get("source") == "Version" and log.get("fieldname") == "processing_status"
		)

		self.assertEqual(status_log["old_value"], "NEW")
		self.assertEqual(status_log["new_value"], "PROCESSING")

	def test_student_lead_handoff_audits_lead_processing_changes(self):
		suffix = frappe.generate_hash(length=8)
		with patch(
			"crm.api.student_school._normalize_lead_payload",
			return_value=(
				{
					"student_name": f"Audit Handoff Student {suffix}",
					"phone": f"091234{len(suffix):04d}",
					"email": f"audit-handoff-{suffix}@example.com",
					"province": "Hà Nội",
				},
				[],
				[],
				None,
			),
		):
			result = create_student_with_lead(
				{
					"student_name": f"Audit Handoff Student {suffix}",
					"phone": f"091234{len(suffix):04d}",
					"email": f"audit-handoff-{suffix}@example.com",
				}
			)

		lead_result = get_lead_audit_logs(result["lead"]["name"], page_length=100)
		status_log = next(
			log
			for log in lead_result["logs"]
			if log.get("source") == "Version" and log.get("fieldname") == "processing_status"
		)

		self.assertEqual(status_log["old_value"], "NEW")
		self.assertEqual(status_log["new_value"], "CLOSED")

	def test_student_audit_includes_related_activity_records(self):
		suffix = frappe.generate_hash(length=8)
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"student_name": f"Audit Related Student {suffix}",
				"phone": "0912345690",
				"email": f"audit-related-{suffix}@example.com",
			}
		).insert(ignore_permissions=True)
		student = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"source_lead": lead.name,
				"full_name": f"Audit Related Student {suffix}",
				"phone": "0912345690",
				"email": f"audit-related-{suffix}@example.com",
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": "CRM Lead",
				"reference_name": lead.name,
				"content": "Phụ huynh đã phản hồi qua bình luận.",
			}
		).insert(ignore_permissions=True)
		note = frappe.get_doc(
			{
				"doctype": "FCRM Note",
				"reference_doctype": "CRM Lead",
				"reference_docname": lead.name,
				"content": "Ghi chú tư vấn tuyển sinh.",
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "Email",
				"sent_or_received": "Received",
				"subject": "Email follow-up",
				"content": "Nội dung email follow-up.",
				"reference_doctype": "CRM Lead",
				"reference_name": lead.name,
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Call Log",
				"id": f"audit-{suffix}",
				"type": "Outgoing",
				"status": "Completed",
				"from": "+84901111111",
				"to": "+84902222222",
				"reference_doctype": "CRM Lead",
				"reference_docname": lead.name,
				"note": note.name,
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Task",
				"title": "Audit follow-up task",
				"description": "Gọi lại cho phụ huynh.",
				"status": "Todo",
				"priority": "Medium",
				"assigned_to": "Administrator",
				"reference_doctype": "CRM Lead",
				"reference_docname": lead.name,
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "audit-related.txt",
				"file_url": "https://example.com/audit-related.txt",
				"attached_to_doctype": "CRM Lead",
				"attached_to_name": lead.name,
			}
		).insert(ignore_permissions=True)

		result = get_student_audit_logs(student.name, page_length=100)
		logs = result["logs"]

		self.assertTrue(any(log["source"] == "Comment" and log.get("content") for log in logs))
		self.assertTrue(any(log["source"] == "Communication" and log.get("subject") for log in logs))
		self.assertTrue(any(log["source"] == "File" for log in logs))
		self.assertTrue(any(log["source"] == "Call Log" for log in logs))
		self.assertTrue(any(log["source"] == "FCRM Note" and log.get("content") for log in logs))
		self.assertTrue(any(log["source"] == "Task" and log.get("subject") for log in logs))
		self.assertEqual(len(logs), result["total"])

	def test_lead_audit_contract_exposes_lead_id(self):
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"student_name": "Lead Audit API",
				"phone": "0912345682",
				"email": "lead-audit-api@example.com",
			}
		).insert(ignore_permissions=True)

		result = get_lead_audit_logs(lead.name)

		self.assertEqual(result["lead_id"], lead.name)
		self.assertTrue(result["read_only"])
		self.assertIn("created", [log["action"] for log in result["logs"]])

	def test_student_audit_uses_canonical_student_as_primary_aggregate(self):
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"student_name": "Canonical Audit Student",
				"phone": "0912345683",
				"email": "canonical-audit-api@example.com",
			}
		).insert(ignore_permissions=True)

		student = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"source_lead": lead.name,
				"full_name": "Canonical Audit Student",
				"phone": "0912345683",
				"email": "canonical-audit-api@example.com",
			}
		).insert(ignore_permissions=True)

		result = get_student_audit_logs(student.name)

		self.assertEqual(result["student"], student.name)
		self.assertTrue(result["logs"])

	def test_segment_audit_returns_segment_creation_and_field_changes(self):
		segment = frappe.get_doc({"doctype": "CRM Segment", "title": "Audit API Segment"}).insert(
			ignore_permissions=True
		)

		segment.title = "Updated Audit API Segment"
		segment.save(ignore_permissions=True, ignore_version=False)
		create_task("CRM Segment", segment.name, "Review segment audience")

		result = get_segment_audit_logs(segment.name, page_length=100)
		updated = next(
			log for log in result["logs"] if log["action"] == "updated" and log["fieldname"] == "title"
		)

		self.assertEqual(result["segment"], segment.name)
		self.assertIn("created", [log["action"] for log in result["logs"]])
		self.assertEqual(updated["old_value"], "Audit API Segment")
		self.assertEqual(updated["new_value"], "Updated Audit API Segment")
		self.assertTrue(any(log["source"] == "CRM Action Item" for log in result["logs"]))
		self.assertTrue(result["read_only"])
