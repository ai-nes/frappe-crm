from crm.fcrm.lookup_doctype import LookupDocument


class CRMEnrollmentStatus(LookupDocument):
	"""CRM Enrollment Status - working status for a Contact/Student.

	Carries the funnel classification the AI lead-scoring service reads:
	``stage_category`` (open / enrolled / lost) marks terminal statuses, and
	``lifecycle_stage`` maps the working status onto the long-term funnel.
	"""

	pass
