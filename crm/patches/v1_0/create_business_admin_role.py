"""Retired historical Business Admin patch.

The module and its registration stay in place so an already-applied patch
chain remains stable. The current control plane uses Administrator for rule
management and AI Service for read-only catalog access; this historical step
must not create a new Business Admin role on a later migrate.
"""


def execute():
	return
