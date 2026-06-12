import json

import frappe


STUDENT_SIDE_PANEL_LAYOUT = [
	{
		"label": "Details",
		"name": "details_section",
		"opened": True,
		"columns": [
			{
				"name": "col_main",
				"fields": ["student_name", "phone", "email", "enrollment_status", "branch"],
			}
		],
	},
	{
		"label": "Admission",
		"name": "admission_section",
		"opened": True,
		"columns": [
			{
				"name": "col_admission",
				"fields": [
					"high_school",
					"major",
					"aspiration",
					"source",
					"province",
					"ward",
					"admission_year",
				],
			}
		],
	},
	{
		"label": "Academic & Scores",
		"name": "section_academic_history",
		"opened": True,
		"columns": [
			{
				"name": "col_scores",
				"fields": [
					"cohort_start_year",
					"cohort_end_year",
					"education_program",
					"admission_method",
					"graduation_score",
					"transcript_score",
					"english_converted_score",
					"total_score",
				],
			}
		],
	},
]


STUDENT_DATA_FIELDS_LAYOUT = [
	{
		"name": "first_tab",
		"sections": [
			{
				"label": "Details",
				"name": "details_section",
				"opened": True,
				"columns": [
					{"name": "col_main", "fields": ["student_name", "phone", "email"]},
					{"name": "col_status", "fields": ["enrollment_status", "branch"]},
				],
			},
			{
				"label": "Admission",
				"name": "admission_section",
				"opened": True,
				"columns": [
					{"name": "col_academic", "fields": ["high_school", "major", "aspiration"]},
					{"name": "col_location", "fields": ["source", "province", "ward", "admission_year"]},
				],
			},
			{
				"label": "Academic & Scores",
				"name": "section_academic_history",
				"opened": True,
				"columns": [
					{
						"name": "col_scores1",
						"fields": [
							"cohort_start_year",
							"education_program",
							"graduation_score",
							"transcript_score",
						],
					},
					{
						"name": "col_scores2",
						"fields": [
							"cohort_end_year",
							"admission_method",
							"english_converted_score",
							"total_score",
						],
					},
				],
			},
			{
				"label": "Results",
				"name": "section_academic_tables",
				"opened": True,
				"columns": [
					{"name": "col_tables", "fields": ["academic_results", "language_certificates"]}
				],
			},
			{
				"label": "Notes",
				"name": "notes_section",
				"opened": True,
				"columns": [{"name": "col_notes", "fields": ["notes"]}],
			},
		],
	}
]


def execute():
	_upsert_layout("CRM Student", "Side Panel", "CRM Student-Side Panel", STUDENT_SIDE_PANEL_LAYOUT)
	_upsert_layout("CRM Student", "Data Fields", "CRM Student-Data Fields", STUDENT_DATA_FIELDS_LAYOUT)
	frappe.clear_cache(doctype="Fields Layout")


def _upsert_layout(doctype, layout_type, name, layout):
	if frappe.db.exists("Fields Layout", name):
		doc = frappe.get_doc("Fields Layout", name)
	elif frappe.db.exists("Fields Layout", {"dt": doctype, "type": layout_type}):
		doc = frappe.get_doc("Fields Layout", {"dt": doctype, "type": layout_type})
	else:
		doc = frappe.new_doc("Fields Layout")

	doc.update({
		"doctype": "Fields Layout",
		"dt": doctype,
		"type": layout_type,
		"layout": json.dumps(layout, ensure_ascii=False),
	})
	if not doc.name:
		doc.name = name
	doc.save(ignore_permissions=True)
