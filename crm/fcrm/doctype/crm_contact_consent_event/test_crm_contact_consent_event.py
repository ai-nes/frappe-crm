from unittest.mock import Mock

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.doctype.crm_contact_consent_event.crm_contact_consent_event import CRMContactConsentEvent


class TestCRMContactConsentEvent(FrappeTestCase):
	def test_grant_requires_exactly_one_subject(self):
		doc = CRMContactConsentEvent({"event_type": "Granted", "granted_at": frappe.utils.now_datetime()})

		with self.assertRaises(frappe.ValidationError):
			doc.validate()

	def test_grant_subject_and_payload_are_immutable_after_insert(self):
		doc = CRMContactConsentEvent(
			{
				"event_type": "Granted",
				"student": "STU-1",
				"purpose": "student_intake",
				"scope": "admissions",
				"granted_at": frappe.utils.now_datetime(),
				"source": "chatwoot",
			}
		)
		doc.get_doc_before_save = Mock(
			return_value=CRMContactConsentEvent(
				{
					"event_type": "Granted",
					"student": "STU-2",
					"purpose": "student_intake",
					"scope": "admissions",
					"granted_at": doc.granted_at,
					"source": "chatwoot",
				}
			)
		)
		doc.is_new = Mock(return_value=False)

		with self.assertRaises(frappe.ValidationError):
			doc.validate()
