# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.model.document import Document

from crm.install import after_install


class FCRMSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.desk.doctype.event_notifications.event_notifications import EventNotifications
		from frappe.types import DF

		from crm.fcrm.doctype.dropdown_item.dropdown_item import DropdownItem

		access_key: DF.Data | None
		all_day_event_notifications: DF.Table[EventNotifications]
		auto_mark_replied_on_response: DF.Check
		auto_reopen_on_new_communication: DF.Check
		brand_logo: DF.Attach | None
		brand_name: DF.Data | None
		currency: DF.Link | None
		default_calendar_view: DF.Literal["Daily", "Weekly", "Monthly"]
		dropdown_items: DF.Table[DropdownItem]
		event_notifications: DF.Table[EventNotifications]
		favicon: DF.Attach | None
		service_provider: DF.Literal[
			"frankfurter.app", "fawazahmed-exchange-api", "exchangerate.host", "exchangerate-api"
		]
		update_timestamp_on_new_communication: DF.Check
	# end: auto-generated types

	@frappe.whitelist()
	def restore_defaults(self, force: bool = False):
		after_install(force)

	def validate(self):
		self.do_not_allow_to_delete_if_standard()
		self.make_currency_read_only()

	def do_not_allow_to_delete_if_standard(self):
		if not self.has_value_changed("dropdown_items"):
			return
		old_items = self.get_doc_before_save().get("dropdown_items")
		standard_new_items = [d.name1 for d in self.dropdown_items if d.is_standard]
		standard_old_items = [d.name1 for d in old_items if d.is_standard]
		deleted_standard_items = set(standard_old_items) - set(standard_new_items)
		if deleted_standard_items:
			standard_dropdown_items = get_standard_dropdown_items()
			if not deleted_standard_items.intersection(standard_dropdown_items):
				return
			frappe.throw(_("Cannot delete standard items {0}").format(", ".join(deleted_standard_items)))

	def make_currency_read_only(self):
		if self.currency and self.has_value_changed("currency"):
			make_property_setter(
				"FCRM Settings",
				"currency",
				"read_only",
				1,
				"Check",
			)


def get_standard_dropdown_items():
	return [item.get("name1") for item in frappe.get_hooks("standard_dropdown_items")]


def after_migrate():
	sync_table("dropdown_items", "standard_dropdown_items")
	if not frappe.db.get_single_value("System Settings", "language"):
		frappe.db.set_single_value("System Settings", "language", "vi")



def sync_table(key, hook):
	crm_settings = FCRMSettings("FCRM Settings")
	existing_items = {d.name1: d for d in crm_settings.get(key)}
	new_standard_items = {}

	# add new items
	count = 0  # maintain count because list may come from seperate apps
	for item in frappe.get_hooks(hook):
		if item.get("name1") not in existing_items:
			crm_settings.append(key, item, count)
		new_standard_items[item.get("name1")] = True
		count += 1

	# remove unused items
	items = crm_settings.get(key)
	items = [item for item in items if not (item.is_standard and (item.name1 not in new_standard_items))]
	crm_settings.set(key, items)

	crm_settings.save()

