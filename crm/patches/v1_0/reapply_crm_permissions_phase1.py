"""Re-runs setup_crm_permissions.execute() under a distinct patch identifier.

crm.patches.v1_0.setup_crm_permissions already exists earlier in patches.txt and
has already run (and been logged in Patch Log) on any site migrated before Phase 1.
Since Frappe's patch runner dedupes by exact module path, simply re-adding that
same path a second time would silently no-op on those sites — so the Phase 1
changes to setup_crm_permissions.py (if_owner removed from Sale/CTV-Sale on CRM
Student, new Admissions Operations/Director rows) would never actually apply.
This wrapper gives the re-run its own patch key so it always executes.
"""

from crm.patches.v1_0.setup_crm_permissions import execute as setup_crm_permissions_execute


def execute():
	setup_crm_permissions_execute()
