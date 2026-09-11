"""Migrate the flat special-profile selection model and enforce one profile per application."""

from __future__ import annotations

import frappe

from crm.patches.v1_0 import seed_admission_profile_template_catalog

SPECIAL_OPTION_DOCTYPE = "CRM Admission Application Special Profile"
SPECIAL_OPTION_FIELD = "special_profile_options"
APPLICATION_PROFILE_INDEX = "crm_student_admission_profile_application_uniq"


def execute() -> None:
	if not frappe.db.table_exists("CRM Admission Profile Template"):
		return

	seed_admission_profile_template_catalog.execute()
	_synchronize_standard_template()
	_migrate_legacy_special_program_template()
	_migrate_legacy_scholarship_template()
	_repair_application_profile_duplicates()
	_add_application_profile_unique_index()

	for doctype in (
		"CRM Admission Application",
		"CRM Admission Profile Template",
		"CRM Student Admission Profile",
	):
		frappe.clear_cache(doctype=doctype)


def _synchronize_standard_template() -> None:
	standard_name = frappe.db.get_value(
		"CRM Admission Profile Template", {"template_code": "STANDARD"}, "name"
	)
	if not standard_name:
		return
	template = frappe.get_doc("CRM Admission Profile Template", standard_name)
	previous_flag = getattr(frappe.flags, "admission_profile_template_admin_update", False)
	frappe.flags.admission_profile_template_admin_update = True
	try:
		template.template_kind = "standard"
		template.template_name = "Hồ sơ thông thường"
		template.set("document_types", seed_admission_profile_template_catalog._rows("STANDARD"))
		template.save(ignore_permissions=True)
	finally:
		frappe.flags.admission_profile_template_admin_update = previous_flag


def _migrate_legacy_scholarship_template() -> None:
	"""Turn the old scholarship template into the new selectable special option."""
	standard_name = frappe.db.get_value(
		"CRM Admission Profile Template", {"template_code": "STANDARD"}, "name"
	)
	scholarship_name = frappe.db.get_value(
		"CRM Admission Profile Template", {"template_code": "SCHOLARSHIP"}, "name"
	)
	if not standard_name or not scholarship_name:
		return

	legacy_references = [scholarship_name, "SCHOLARSHIP"]
	application_rows = frappe.get_all(
		"CRM Admission Application",
		filters={"profile_template": ["in", legacy_references]},
		fields=["name"],
		limit_page_length=0,
		ignore_permissions=True,
	)
	for application in application_rows:
		_application_add_scholarship_option(application.name, scholarship_name)
		frappe.db.set_value(
			"CRM Admission Application",
			application.name,
			"profile_template",
			standard_name,
			update_modified=False,
		)

	profile_rows = frappe.get_all(
		"CRM Student Admission Profile",
		filters={"profile_template": ["in", legacy_references]},
		fields=["name", "application"],
		limit_page_length=0,
		ignore_permissions=True,
	)
	for profile in profile_rows:
		frappe.db.set_value(
			"CRM Student Admission Profile",
			profile.name,
			"profile_template",
			standard_name,
			update_modified=False,
		)
		if profile.application:
			frappe.db.set_value(
				"CRM Student Admission Profile",
				profile.name,
				"attempt_key",
				f"application:{profile.application}",
				update_modified=False,
			)

	template = frappe.get_doc("CRM Admission Profile Template", scholarship_name)
	if (template.template_kind or "standard") == "special":
		return
	previous_flag = getattr(frappe.flags, "admission_profile_template_admin_update", False)
	frappe.flags.admission_profile_template_admin_update = True
	try:
		template.template_kind = "special"
		template.template_name = "Diện học bổng"
		template.set("document_types", seed_admission_profile_template_catalog._rows("SCHOLARSHIP"))
		template.save(ignore_permissions=True)
	finally:
		frappe.flags.admission_profile_template_admin_update = previous_flag


def _migrate_legacy_special_program_template() -> None:
	"""Split the former bundled special-program template into flat options."""
	standard_name = frappe.db.get_value(
		"CRM Admission Profile Template", {"template_code": "STANDARD"}, "name"
	)
	legacy_name = frappe.db.get_value(
		"CRM Admission Profile Template", {"template_code": "SPECIAL_PROGRAM"}, "name"
	)
	if not standard_name or not legacy_name:
		return

	option_names = [
		frappe.db.get_value("CRM Admission Profile Template", {"template_code": code}, "name")
		for code in ("FIRST_GENERATION", "STUDY_NOW_PAY_LATER", "FAMILY_FE_FPT")
	]
	option_names = [name for name in option_names if name]
	legacy_references = [legacy_name, "SPECIAL_PROGRAM"]
	application_rows = frappe.get_all(
		"CRM Admission Application",
		filters={"profile_template": ["in", legacy_references]},
		fields=["name"],
		limit_page_length=0,
		ignore_permissions=True,
	)
	for application in application_rows:
		for option_name in option_names:
			_application_add_special_option(application.name, option_name)
		frappe.db.set_value(
			"CRM Admission Application",
			application.name,
			"profile_template",
			standard_name,
			update_modified=False,
		)

	profile_rows = frappe.get_all(
		"CRM Student Admission Profile",
		filters={"profile_template": ["in", legacy_references]},
		fields=["name", "application"],
		limit_page_length=0,
		ignore_permissions=True,
	)
	for profile in profile_rows:
		frappe.db.set_value(
			"CRM Student Admission Profile",
			profile.name,
			"profile_template",
			standard_name,
			update_modified=False,
		)
		if profile.application:
			frappe.db.set_value(
				"CRM Student Admission Profile",
				profile.name,
				"attempt_key",
				f"application:{profile.application}",
				update_modified=False,
			)


def _application_add_scholarship_option(application_name: str, template_name: str) -> None:
	_application_add_special_option(application_name, template_name)


def _application_add_special_option(application_name: str, template_name: str) -> None:
	if not frappe.db.table_exists(SPECIAL_OPTION_DOCTYPE):
		return
	if frappe.db.exists(
		SPECIAL_OPTION_DOCTYPE,
		{"parent": application_name, "special_profile_template": template_name},
	):
		return
	selection_order = frappe.db.count(SPECIAL_OPTION_DOCTYPE, {"parent": application_name}) + 1
	frappe.get_doc(
		{
			"doctype": SPECIAL_OPTION_DOCTYPE,
			"parent": application_name,
			"parenttype": "CRM Admission Application",
			"parentfield": SPECIAL_OPTION_FIELD,
			"special_profile_template": template_name,
			"selection_order": selection_order,
		}
	).insert(ignore_permissions=True)


def _repair_application_profile_duplicates() -> None:
	if not frappe.db.table_exists("CRM Student Admission Profile"):
		return
	duplicate_applications = frappe.db.sql(
		"""
		SELECT application
		FROM `tabCRM Student Admission Profile`
		WHERE application IS NOT NULL AND application != ''
		GROUP BY application
		HAVING COUNT(*) > 1
		""",
		as_dict=True,
	)
	for row in duplicate_applications:
		profiles = frappe.get_all(
			"CRM Student Admission Profile",
			filters={"application": row.application},
			fields=["name", "profile_status", "modified"],
			order_by="modified desc, name desc",
			limit_page_length=0,
			ignore_permissions=True,
		)
		if len(profiles) < 2:
			continue
		keeper = _select_profile_keeper(profiles)
		for profile in profiles:
			if profile.name == keeper.name:
				continue
			frappe.db.set_value(
				"CRM Student Admission Profile",
				profile.name,
				{
					"profile_status": "Archived",
					"application": None,
					"attempt_key": f"legacy:{profile.name}",
				},
				update_modified=True,
			)

	frappe.db.sql(
		"""
		UPDATE `tabCRM Student Admission Profile`
		SET attempt_key = CONCAT('application:', application)
		WHERE application IS NOT NULL AND application != ''
		"""
	)


def _select_profile_keeper(profiles):
	status_priority = {"Active": 4, "Completed": 3, "Draft": 2, "Archived": 1}
	return max(
		profiles,
		key=lambda profile: (status_priority.get(profile.profile_status, 0), profile.modified, profile.name),
	)


def _add_application_profile_unique_index() -> None:
	physical_table = "tabCRM Student Admission Profile"
	if not frappe.db.table_exists("CRM Student Admission Profile"):
		return
	if frappe.db.sql(f"SHOW INDEX FROM `{physical_table}` WHERE Key_name = %s", APPLICATION_PROFILE_INDEX):
		return
	frappe.db.sql_ddl(
		f"ALTER TABLE `{physical_table}` ADD UNIQUE INDEX `{APPLICATION_PROFILE_INDEX}` (`application`)"
	)
