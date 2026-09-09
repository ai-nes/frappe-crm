"""Assign an admissions ``funnel_stage`` to every seeded ``CRM Intent Type``.

The Intent Evolution engine (crm-agents) maps each intent to a funnel stage to
compute a trajectory slope. This patch backfills the axis for rows that already
exist on an upgraded site. A fresh site marks every historical patch complete,
so ``crm/install.py`` calls ``execute()`` again from ``after_install`` (right
after ``seed_reference_lookups``) to give a new site the same mapping.

Conservative: only the obvious admissions mappings are set. Ambiguous codes and
operator-defined intents are left blank -- the engine treats blank as
``unknown`` and drops them from the slope.

Idempotent: a row that already has a ``funnel_stage`` is never overwritten.
"""

import frappe

# code -> funnel_stage. Stages: awareness, interest, consideration, objection,
# intent, enrolled, churn_risk. (Proposed enum; confirm with admissions.)
_FUNNEL_STAGE_BY_CODE = {
	"PROGRAM_INTEREST": "interest",
	"CAREER_COUNSELING": "interest",
	"CAMPUS_INFORMATION": "interest",
	"STUDENT_LIFE": "interest",
	"REQUEST_CONTACT": "interest",
	"MAJOR_INQUIRY": "interest",
	"ENVIRONMENT": "interest",
	"DORMITORY": "interest",
	"ADMISSION_REQUIREMENT": "consideration",
	"TUITION_FEE": "consideration",
	"TUITION": "consideration",
	"SCHOLARSHIP": "consideration",
	"DEADLINE": "consideration",
	"ADMISSION_PROCESS": "consideration",
	"APPLICATION_GUIDANCE": "intent",
	"APPLICATION_STATUS": "intent",
	"DOCUMENT_REQUIREMENT": "intent",
	"ENROLLMENT_INTENT": "intent",
	"DEPOSIT_INTENT": "intent",
	"ENROLLMENT_CONFIRMATION": "enrolled",
	"WITHDRAWAL_OR_HESITATION": "objection",
	"NOT_INTERESTED": "churn_risk",
}


def execute():
	if not frappe.db.has_column("CRM Intent Type", "funnel_stage"):
		return
	for code, stage in _FUNNEL_STAGE_BY_CODE.items():
		if not frappe.db.exists("CRM Intent Type", code):
			continue
		if frappe.db.get_value("CRM Intent Type", code, "funnel_stage"):
			continue
		frappe.db.set_value("CRM Intent Type", code, "funnel_stage", stage, update_modified=False)

	if not getattr(frappe.flags, "in_test", False):
		frappe.db.commit()
