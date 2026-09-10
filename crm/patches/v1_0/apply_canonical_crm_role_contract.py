"""Apply canonical CRM role aliases to sites that already logged setup patches."""

from crm.patches.v1_0.setup_crm_permissions import execute as apply_permissions
from crm.patches.v1_0.setup_crm_roles import NEW_ROLES, create_roles


def execute():
	create_roles(NEW_ROLES)
	apply_permissions()
