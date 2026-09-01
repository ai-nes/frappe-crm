from frappe.model.document import Document

from crm.fcrm.analysis_runs import validate_run_fields


class CRMStudentAnalysisRun(Document):
	def validate(self):
		validate_run_fields(self)
