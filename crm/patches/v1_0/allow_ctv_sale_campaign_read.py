"""Grant CTV Sale read access to CRM Campaign on existing sites."""

from crm.patches.v1_0.seed_new_lead_role_profiles import execute as seed_role_profiles


def execute():
	seed_role_profiles()
