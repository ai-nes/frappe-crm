from crm.install import sync_frappe_crm_workspace


def execute():
	"""Re-import Frappe CRM workspace after frappe_crm.json was restored to the repo."""
	sync_frappe_crm_workspace()
