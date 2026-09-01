from frappe.model.document import Document

from crm.fcrm.analysis_runs import validate_claim_set, validate_stage_fields


class CRMAnalysisRunStage(Document):
	def validate(self):
		validate_stage_fields(self)
		validate_claim_set(self.get("claims"))
