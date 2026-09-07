"""Ensure the current CRM Action slot fence survives fresh-site schema sync."""

from crm.patches.v1_0.crm_action_current_slot_unique import execute as ensure_current_slot_unique


def execute():
	"""Re-run the idempotent current-slot migration after all DocTypes are synced."""
	ensure_current_slot_unique()
