"""Grant Guest read access to the public school-detail reference data."""

from crm.patches.v1_0.setup_crm_permissions import apply_managed_docperms


def execute():
	"""Synchronize the idempotent policy adapter after adding public reads."""
	apply_managed_docperms()
