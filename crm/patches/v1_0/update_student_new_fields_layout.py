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
				"fields": ["student_name", "phone", "email", "enrollment_status", "branch", "gender", "date_of_birth"],
			}
		],
	},
	{
		"label": "Identity",
		"name": "identity_section",
		"opened": False,
		"columns": [
			{
				"name": "col_identity",
				"fields": ["id_number", "id_issued_date", "id_issued_place", "import_source_id"],
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
					"step",
				],
			}
		],
	},
	{
		"label": "Parent Info",
		"name": "parent_section",
		"opened": True,
		"columns": [
			{
				"name": "col_parent",
				"fields": ["alt_name", "alt_phone", "alt_address"],
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
					{"name": "col_main", "fields": ["student_name", "phone", "email", "gender"]},
					{"name": "col_status", "fields": ["enrollment_status", "branch", "date_of_birth"]},
				],
			},
			{
				"label": "Identity",
				"name": "identity_section",
				"opened": False,
				"columns": [
					{"name": "col_id1", "fields": ["id_number", "id_issued_date"]},
					{"name": "col_id2", "fields": ["id_issued_place", "import_source_id"]},
				],
			},
			{
				"label": "Admission",
				"name": "admission_section",
				"opened": True,
				"columns": [
					{"name": "col_academic", "fields": ["high_school", "major", "aspiration", "step"]},
					{"name": "col_location", "fields": ["source", "province", "ward", "admission_year"]},
				],
			},
			{
				"label": "Thông tin phụ huynh",
				"name": "parent_section",
				"opened": True,
				"columns": [
					{"name": "col_parent1", "fields": ["alt_name", "alt_phone"]},
					{"name": "col_parent2", "fields": ["alt_address"]},
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
	existing_name = frappe.db.get_value("Fields Layout", name, "name") or frappe.db.get_value(
		"Fields Layout", {"dt": doctype, "type": layout_type}, "name"
	)
	doc = frappe.get_doc("Fields Layout", existing_name) if existing_name else frappe.new_doc("Fields Layout")
	doc.update({
		"dt": doctype,
		"type": layout_type,
		"layout": json.dumps(layout, ensure_ascii=False),
	})
	if not doc.name:
		doc.name = name
	doc.save(ignore_permissions=True)
