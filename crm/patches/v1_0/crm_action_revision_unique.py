"""Retain the historical patch slot after action-package history removal."""


def execute():
	"""Retired with the temporary action-package history table.

	The patch remains in the historical patch list so fresh benches can replay
	the list; the consolidation patch owns the data migration and table drop.
	"""
	return None
