# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class Dashboard(Document):
	pass


def default_manager_dashboard_layout():
	"""
	Returns the default layout for the CRM Manager Dashboard.
	"""
	return '[{"name":"total_students","type":"number_chart","tooltip":"Total number of imported enrollment students","layout":{"x":0,"y":0,"w":4,"h":3,"i":"total_students"}},{"name":"total_contacts","type":"number_chart","tooltip":"Total number of admission contacts","layout":{"x":4,"y":0,"w":4,"h":3,"i":"total_contacts"}},{"name":"qualified_contacts","type":"number_chart","tooltip":"Contacts currently in the qualified stage","layout":{"x":8,"y":0,"w":4,"h":3,"i":"qualified_contacts"}},{"name":"enrolled_contacts","type":"number_chart","tooltip":"Contacts currently in the enrolled stage","layout":{"x":12,"y":0,"w":4,"h":3,"i":"enrolled_contacts"}},{"name":"spacer","type":"spacer","layout":{"x":16,"y":0,"w":4,"h":3,"i":"spacer"}},{"name":"admission_trend","type":"axis_chart","layout":{"x":0,"y":4,"w":10,"h":9,"i":"admission_trend"}},{"name":"contacts_by_stage","type":"donut_chart","layout":{"x":10,"y":4,"w":10,"h":9,"i":"contacts_by_stage"}},{"name":"contacts_by_source","type":"donut_chart","layout":{"x":0,"y":13,"w":10,"h":9,"i":"contacts_by_source"}},{"name":"students_by_source","type":"donut_chart","layout":{"x":10,"y":13,"w":10,"h":9,"i":"students_by_source"}},{"name":"contacts_by_high_school","type":"axis_chart","layout":{"x":0,"y":22,"w":10,"h":9,"i":"contacts_by_high_school"}},{"name":"contacts_by_assignee","type":"axis_chart","layout":{"x":10,"y":22,"w":10,"h":9,"i":"contacts_by_assignee"}}]'


def create_default_manager_dashboard(force=False):
	"""
	Creates the default CRM Manager Dashboard if it does not exist.
	"""
	if not frappe.db.exists("Dashboard", "Manager Dashboard"):
		doc = frappe.new_doc("Dashboard")
		doc.title = "Manager Dashboard"
		doc.layout = default_manager_dashboard_layout()
		doc.insert(ignore_permissions=True)
	else:
		doc = frappe.get_doc("Dashboard", "Manager Dashboard")
		if force:
			doc.layout = default_manager_dashboard_layout()
			doc.save(ignore_permissions=True)
	return doc.layout
