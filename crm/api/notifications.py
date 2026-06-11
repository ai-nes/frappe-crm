import frappe
from frappe.query_builder import Order


ROUTES_BY_DOCTYPE = {
	"CRM Contact": ("CRM Contact", "crmContactId", "crm contact"),
	"CRM Student": ("CRM Student", "crmStudentId", "student"),
	"CRM Person": ("CRM Person", "crm_personId", "crm_person"),
	"CRM High School": ("High School", "highSchoolId", "high school"),
	"CRM Campaign": ("CRM Campaign", "crm_campaignId", "crm_campaign"),
	"CRM Event": ("CRM Event", "crmEventId", "crm event"),
	"Task": ("Tasks", None, "task"),
	"Contact": ("Contact", "contactId", "contact"),
}


@frappe.whitelist()
def get_notifications():
	Notification = frappe.qb.DocType("Notification")
	query = (
		frappe.qb.from_(Notification)
		.select("*")
		.where(Notification.to_user == frappe.session.user)
		.orderby("creation", order=Order.desc)
	)
	notifications = query.run(as_dict=True)

	_notifications = []
	for notification in notifications:
		route_name, param_name, reference_doctype = get_route(notification.reference_doctype)
		_notifications.append(
			{
				"creation": notification.creation,
				"from_user": {
					"name": notification.from_user,
					"full_name": frappe.get_value("User", notification.from_user, "full_name"),
				},
				"type": notification.type,
				"to_user": notification.to_user,
				"read": notification.read,
				"hash": get_hash(notification),
				"notification_text": notification.notification_text,
				"notification_type_doctype": notification.notification_type_doctype,
				"notification_type_doc": notification.notification_type_doc,
				"reference_doctype": reference_doctype,
				"reference_name": notification.reference_name,
				"route_name": route_name,
				"param_name": param_name,
			}
		)

	return _notifications


@frappe.whitelist()
def mark_as_read(user: str | None = None, doc: str | None = None):
	user = user or frappe.session.user
	filters = {"to_user": user, "read": False}
	or_filters = []
	if doc:
		or_filters = [
			{"comment": doc},
			{"notification_type_doc": doc},
		]
	for n in frappe.get_all("Notification", filters=filters, or_filters=or_filters):
		d = frappe.get_doc("Notification", n.name)
		d.read = True
		d.save()


def get_hash(notification):
	_hash = ""
	if notification.type == "Mention" and notification.notification_type_doc:
		_hash = "#" + notification.notification_type_doc

	if notification.type == "WhatsApp":
		_hash = "#whatsapp"

	if notification.type == "Assignment" and notification.notification_type_doctype == "Task":
		_hash = "#tasks"
		if "has been removed by" in notification.message:
			_hash = ""
	return _hash


def get_route(reference_doctype):
	return ROUTES_BY_DOCTYPE.get(reference_doctype, ("CRM Contacts", None, reference_doctype))
