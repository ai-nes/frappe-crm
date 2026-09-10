"""Backfill CTV Sale read access for the Director projection dependencies.

The CTV Sale profile was introduced before the read-only Director projections
were exposed to that role. Reusing the profile seeder keeps this forward patch
aligned with the DB-backed permission catalog and makes it safe to rerun.
"""

from crm.patches.v1_0.seed_new_lead_role_profiles import execute as seed_role_profiles


def execute():
	seed_role_profiles()
