"""Activate the canonical Need and Tag catalogue on existing sites."""

from crm.fcrm.classification_catalog import seed_catalog


def execute():
	seed_catalog()
