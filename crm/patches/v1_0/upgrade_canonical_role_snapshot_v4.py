"""Create the complete v4 recovery artifact on already-migrated sites.

Older installations may have recorded the one-shot role migration before the
snapshot schema gained its full authorization-reference inventory.  This patch
does not mutate roles; it captures the current canonical state (including all
known role-bearing tables) into the new immutable v4 path so rollback tooling
never silently consumes the incomplete v2 artifact.
"""

from crm.patches.v1_0.migrate_to_canonical_crm_roles import _write_snapshot_once


def execute():
	_write_snapshot_once(capture_mode="post_cutover_recovery")
