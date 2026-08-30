"""Register the admissions ERD baseline without mutating business rows."""


def execute():
	# Patch execution is deliberately a no-op.  Operators call the admin-only
	# profiler after schema sync so the report can be stored in their migration
	# run artifact without putting an unbounded report into patch history.
	return None
