"""Apply role cleanup to sites that migrated before setup_crm_roles changed."""

from crm.patches.v1_0.setup_crm_roles import remove_unused_roles


def execute():
	remove_unused_roles()
