import frappe

NEW_INTENT_TYPES = [
	# Only 2 new categories to keep the AI-interest card grid at 8 total (6 existing + these 2).
	# "Quan tâm" is intentionally NOT a separate category: any of the 7 other intent types already
	# signals interest, so a dedicated "interested" card would be redundant. "Không quan tâm" is the
	# one new, actionable negative signal; its exact name is a hard dependency of the Offline
	# Marketing dashboard's not-interested lead bucket (phase-04 step 4) — do not rename.
	("Không quan tâm", "Medium", "Học sinh thể hiện không quan tâm / từ chối tiếp tục."),
	("Other", "Medium", "Mối quan tâm không thuộc 6 nhóm nội dung hiện có."),
]


def execute():
	for name, importance, description_vi in NEW_INTENT_TYPES:
		if not frappe.db.exists("CRM Intent Type", name):
			frappe.get_doc(
				{
					"doctype": "CRM Intent Type",
					"intent_type_name": name,
					"importance": importance,
					"description_vi": description_vi,
				}
			).insert(ignore_permissions=True)

	frappe.db.commit()
