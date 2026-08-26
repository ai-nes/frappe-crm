app_name = "crm"
app_title = "Frappe CRM"
app_publisher = "Frappe Technologies Pvt. Ltd."
app_description = "Kick-ass Open Source CRM"
app_email = "shariq@frappe.io"
app_license = "AGPLv3"
app_icon_url = "/assets/crm/images/logo.svg"
app_icon_title = "CRM"
app_icon_route = "/crm"

# Apps
# ------------------

# required_apps = []
add_to_apps_screen = [
	{
		"name": "crm",
		"logo": "/assets/crm/images/logo.svg",
		"title": "CRM",
		"route": "/crm",
		"has_permission": "crm.api.check_app_permission",
	}
]

get_site_info = "crm.activation.get_site_info"

export_python_type_annotations = True
require_type_annotated_api_methods = True

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/crm/css/crm.css"
# app_include_js = "/assets/crm/js/crm.js"

# include js, css files in header of web template
# web_include_css = "/assets/crm/css/crm.css"
# web_include_js = "/assets/crm/js/crm.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "crm/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# "Role": "home_page"
# }

website_route_rules = [
	{"from_route": "/crm/<path:app_path>", "to_route": "crm"},
]

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# "methods": "crm.utils.jinja_methods",
# "filters": "crm.utils.jinja_filters"
# }

# Setup wizard
# setup_wizard_requires = "assets/crm/js/setup_wizard.js"
# setup_wizard_stages = "crm.setup.setup_wizard.setup_wizard.get_setup_stages"
setup_wizard_complete = "crm.demo.api.create_demo_data"
# setup_wizard_test = "crm.setup.setup_wizard.test_setup_wizard.run_setup_wizard_test"

# Installation
# ------------

before_install = "crm.install.before_install"
after_install = "crm.install.after_install"

# Uninstallation
# ------------

before_uninstall = "crm.uninstall.before_uninstall"
# after_uninstall = "crm.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "crm.utils.before_app_install"
# after_app_install = "crm.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "crm.utils.before_app_uninstall"
# after_app_uninstall = "crm.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "crm.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

permission_query_conditions = {
	"CRM Contact": "crm.fcrm.doctype.crm_contact.crm_contact.get_permission_query_conditions",
	"CRM Student": "crm.fcrm.doctype.crm_student.crm_student.get_permission_query_conditions",
	"CRM Student Routing Request": "crm.fcrm.permissions.get_operational_record_permission_query_conditions",
	"CRM Student SLA Attempt": "crm.fcrm.permissions.get_operational_record_permission_query_conditions",
	"CRM Student SLA Event": "crm.fcrm.permissions.get_operational_record_permission_query_conditions",
	"CRM Student SLA Delivery": "crm.fcrm.permissions.get_operational_record_permission_query_conditions",
	"CRM Student SLA Delivery Attempt": "crm.fcrm.permissions.get_operational_record_permission_query_conditions",
	"CRM Segment": "crm.fcrm.doctype.crm_segment.crm_segment.get_permission_query_conditions",
	"CRM Recommendation": "crm.fcrm.doctype.crm_recommendation.crm_recommendation.get_permission_query_conditions",
	"CRM Sales Action": "crm.fcrm.doctype.crm_sales_action.crm_sales_action.get_permission_query_conditions",
	"CRM Student Task": "crm.fcrm.doctype.crm_student_task.crm_student_task.get_permission_query_conditions",
	"CRM Campaign Touchpoint": "crm.fcrm.student_attribution.get_permission_query_conditions",
	"CRM Event Participation": "crm.fcrm.student_attribution.get_permission_query_conditions",
	"CRM Student Contact Conversion": "crm.fcrm.doctype.crm_student_contact_conversion.crm_student_contact_conversion.get_permission_query_conditions",
	"CRM Interaction": "crm.fcrm.permissions.get_interaction_permission_query_conditions",
	"CRM Intent": "crm.fcrm.permissions.get_intent_permission_query_conditions",
	"CRM Score History": "crm.fcrm.permissions.get_operational_record_permission_query_conditions",
}

has_permission = {
	"CRM Contact": "crm.fcrm.doctype.crm_contact.crm_contact.has_permission",
	"CRM Student": "crm.fcrm.doctype.crm_student.crm_student.has_permission",
	"CRM Student Routing Request": "crm.fcrm.permissions.has_operational_record_permission",
	"CRM Student SLA Attempt": "crm.fcrm.permissions.has_operational_record_permission",
	"CRM Student SLA Event": "crm.fcrm.permissions.has_operational_record_permission",
	"CRM Student SLA Delivery": "crm.fcrm.permissions.has_operational_record_permission",
	"CRM Student SLA Delivery Attempt": "crm.fcrm.permissions.has_operational_record_permission",
	"CRM Segment": "crm.fcrm.doctype.crm_segment.crm_segment.has_permission",
	"CRM Recommendation": "crm.fcrm.doctype.crm_recommendation.crm_recommendation.has_permission",
	"CRM Sales Action": "crm.fcrm.doctype.crm_sales_action.crm_sales_action.has_permission",
	"CRM Student Task": "crm.fcrm.doctype.crm_student_task.crm_student_task.has_permission",
	"CRM Campaign Touchpoint": "crm.fcrm.student_attribution.has_permission",
	"CRM Event Participation": "crm.fcrm.student_attribution.has_permission",
	"CRM Student Contact Conversion": "crm.fcrm.doctype.crm_student_contact_conversion.crm_student_contact_conversion.has_permission",
	"CRM Interaction": "crm.fcrm.permissions.has_interaction_permission",
	"CRM Intent": "crm.fcrm.permissions.has_intent_permission",
	"CRM Score History": "crm.fcrm.permissions.has_operational_record_permission",
}

# DocType Class
# ---------------
# Override standard doctype classes

override_doctype_class = {
	"Contact": "crm.overrides.contact.CustomContact",
	"Email Template": "crm.overrides.email_template.CustomEmailTemplate",
}

# Status Change Log
# ------------------
# Doctypes whose status field is neither "stage" nor "status" register
# their field name here instead of the generic status_change_log helper
# growing a hardcoded chain of field names per adopter.

status_change_log_field = {
	"CRM Contact": "enrollment_status",
	"CRM Student": "enrollment_status",
}

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"DocType": {
		"validate": ["crm.api.capability.validate_ai_exposed_change"],
	},
	"Contact": {
		"validate": ["crm.api.contact.validate"],
	},
	"CRM Contact": {
		"validate": ["crm.fcrm.doctype.status_change_log.status_change_log.on_change_log_hook"],
		"on_update": ["crm.fcrm.interaction_log.create_interaction_from_contact_update"],
	},
	"CRM Student": {
		"validate": ["crm.fcrm.doctype.status_change_log.status_change_log.on_change_log_hook"],
	},
	"CRM Interaction": {
		"after_insert": ["crm.fcrm.interaction_log.satisfy_student_sla_from_interaction"],
		"on_update": ["crm.fcrm.interaction_log.satisfy_student_sla_from_interaction"],
	},
	"CRM Lead Source": {
		"validate": ["crm.fcrm.master_data_governance.validate_governed_mutation"],
		"on_trash": ["crm.fcrm.master_data_governance.prevent_governed_delete"],
		"before_rename": ["crm.fcrm.master_data_governance.prevent_governed_rename"],
	},
	"CRM Platform": {
		"validate": ["crm.fcrm.master_data_governance.validate_governed_mutation"],
		"on_trash": ["crm.fcrm.master_data_governance.prevent_governed_delete"],
		"before_rename": ["crm.fcrm.master_data_governance.prevent_governed_rename"],
	},
	"CRM Intent Type": {
		"validate": ["crm.fcrm.master_data_governance.validate_governed_mutation"],
		"on_trash": ["crm.fcrm.master_data_governance.prevent_governed_delete"],
		"before_rename": ["crm.fcrm.master_data_governance.prevent_governed_rename"],
	},
	"CRM Lost Reason": {
		"validate": ["crm.fcrm.master_data_governance.validate_governed_mutation"],
		"on_trash": ["crm.fcrm.master_data_governance.prevent_governed_delete"],
		"before_rename": ["crm.fcrm.master_data_governance.prevent_governed_rename"],
	},
	"CRM Campus": {
		"validate": ["crm.fcrm.master_data_governance.validate_governed_mutation"],
		"on_trash": ["crm.fcrm.master_data_governance.prevent_governed_delete"],
		"before_rename": ["crm.fcrm.master_data_governance.prevent_governed_rename"],
	},
	"CRM Campaign Type": {
		"validate": ["crm.fcrm.master_data_governance.validate_governed_mutation"],
		"on_trash": ["crm.fcrm.master_data_governance.prevent_governed_delete"],
		"before_rename": ["crm.fcrm.master_data_governance.prevent_governed_rename"],
	},
	"ToDo": {
		"after_insert": ["crm.api.todo.after_insert"],
		"on_update": ["crm.api.todo.on_update"],
	},
	"Communication": {
		"after_insert": [
			"crm.utils.on_communication_insert",
			"crm.fcrm.interaction_log.create_interaction_from_communication_insert",
		],
		"on_update": [
			"crm.utils.on_communication_update",
			"crm.fcrm.interaction_log.create_interaction_from_communication_update",
		],
		"on_trash": ["crm.fcrm.interaction_log.clear_interaction_reference"],
	},
	"Comment": {
		"after_insert": ["crm.utils.on_comment_insert"],
		"on_update": ["crm.api.comment.on_update"],
	},
	"WhatsApp Message": {
		"validate": ["crm.api.whatsapp.validate"],
		"on_update": ["crm.api.whatsapp.on_update"],
	},
	"CRM Contact Consent Event": {
		"after_insert": [
			"crm.fcrm.doctype.crm_contact_consent_event.crm_contact_consent_event.sync_contact_consent_flag",
			"crm.fcrm.interaction_log.create_interaction_from_consent_event",
		],
		"on_trash": ["crm.fcrm.interaction_log.clear_interaction_reference"],
	},
	"Task": {
		"on_update": ["crm.fcrm.interaction_log.create_interaction_from_task_update"],
		"on_trash": ["crm.fcrm.interaction_log.clear_interaction_reference"],
	},
	"Call Log": {
		"after_insert": ["crm.fcrm.interaction_log.create_interaction_from_call_log_insert"],
		"on_trash": ["crm.fcrm.interaction_log.clear_interaction_reference"],
	},
	# Keep legacy Contact-based attribution activity wired. Student-first
	# attribution commands suppress these dispatchers via their service flag.
	"CRM Event Participation": {
		"after_insert": ["crm.fcrm.interaction_log.create_interaction_from_event_participation_insert"],
		"on_update": ["crm.fcrm.interaction_log.create_interaction_from_event_participation_update"],
		"on_trash": ["crm.fcrm.interaction_log.clear_interaction_reference"],
	},
	"CRM Campaign Touchpoint": {
		"after_insert": ["crm.fcrm.interaction_log.create_interaction_from_campaign_touchpoint_insert"],
		"on_trash": ["crm.fcrm.interaction_log.clear_interaction_reference"],
	},
	"User": {
		"before_validate": ["crm.api.live_demo.validate_user"],
		"validate_reset_password": ["crm.api.live_demo.validate_reset_password"],
	},
}

# Consumer-side enforcement is required because retiring a Link target does
# not cause Frappe to revalidate existing consumer writes automatically.
for _governed_consumer_doctype in (
	"CRM Contact", "CRM Platform", "CRM Student", "CRM Campaign Spend",
	"CRM Campaign", "CRM Intent", "CRM Score Signal", "CRM Department",
	"CRM Staff", "CRM Quota Item", "CRM Student Pool", "CRM Student Routing Request",
	"CRM Student SLA Attempt", "CRM Team", "CRM Tuition Policy Item",
):
	_governed_events = doc_events.setdefault(_governed_consumer_doctype, {})
	_governed_events.setdefault("validate", []).append(
		"crm.fcrm.master_data_governance.validate_governed_references"
	)

# Scheduled Tasks
# ---------------

scheduler_events = {
	"hourly": [
		"crm.api.agent_events.retry_pending_agent_events",
		"crm.api.agent_events.reconcile_student_context_v2",
		"crm.api.agent_events.reconcile_score_input_v1",
	],
	"daily": [
		"crm.fcrm.doctype.crm_student.enrollment_transition.reconcile_enrollment_transitions",
		"crm.fcrm.master_data_governance.expire_break_glass_requests",
	],
	"cron": {
		"*/5 * * * *": ["crm.api.sla.recompute_sla_statuses"],
		"* * * * *": [
			"crm.fcrm.master_data_governance.apply_effective_changes",
			"crm.fcrm.student_routing.process_pending_routing_requests",
			"crm.fcrm.student_sla.process_due_sla_attempts",
			"crm.fcrm.student_sla.process_pending_sla_deliveries",
		],
	},
}

# Testing
# -------

before_tests = "crm.tests.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# "frappe.desk.doctype.event.event.get_events": "crm.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# "Task": "crm.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

ignore_links_on_delete = []

# Request Events
# ----------------
before_request = ["crm.api.resource.normalize_resource_phone_filters"]
# after_request = ["crm.utils.after_request"]

# Job Events
# ----------
# before_job = ["crm.utils.before_job"]
# after_job = ["crm.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# {
# "doctype": "{doctype_1}",
# "filter_by": "{filter_by}",
# "redact_fields": ["{field_1}", "{field_2}"],
# "partial": 1,
# },
# {
# "doctype": "{doctype_2}",
# "filter_by": "{filter_by}",
# "partial": 1,
# },
# {
# "doctype": "{doctype_3}",
# "strict": False,
# },
# {
# "doctype": "{doctype_4}"
# }
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# "crm.auth.validate"
# ]

after_migrate = [
	"crm.fcrm.doctype.fcrm_settings.fcrm_settings.after_migrate",
	"crm.api.whatsapp.add_roles",
	"crm.api.agent_migrations.after_migrate",
]

standard_dropdown_items = [
	{
		"name1": "app_selector",
		"label": "Apps",
		"type": "Route",
		"route": "#",
		"is_standard": 1,
	},
	{
		"name1": "settings",
		"label": "Settings",
		"type": "Route",
		"icon": "settings",
		"route": "#",
		"is_standard": 1,
	},
	{
		"name1": "login_to_fc",
		"label": "Login to Frappe Cloud",
		"type": "Route",
		"route": "#",
		"is_standard": 1,
	},
	{
		"name1": "about",
		"label": "About",
		"type": "Route",
		"icon": "info",
		"route": "#",
		"is_standard": 1,
	},
	{
		"name1": "separator",
		"label": "",
		"type": "Separator",
		"is_standard": 1,
	},
	{
		"name1": "logout",
		"label": "Log out",
		"type": "Route",
		"icon": "log-out",
		"route": "#",
		"is_standard": 1,
	},
]
