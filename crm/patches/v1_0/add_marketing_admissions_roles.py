import frappe

from crm.fcrm.role_policy import CRM_POLICY_ROLE_NAMES
from crm.patches.v1_0.setup_crm_roles import create_roles


def execute():
	create_roles(CRM_POLICY_ROLE_NAMES)
