"""Repair Lead ownership fields omitted by the original one-time backfill."""


def execute():
	from crm.patches.v1_0.backfill_owner_fields_from_assigned_to import execute as backfill_owner_fields

	backfill_owner_fields()
