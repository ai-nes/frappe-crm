"""Pure execution-attempt identities and transition contract."""
import hashlib
import json

TERMINAL = {"confirmed", "failed", "cancelled"}
TRANSITIONS = {"pending": {"queued", "cancelled"}, "queued": {"confirmed", "failed", "cancelled"}, "confirmed": set(), "failed": set(), "cancelled": set()}

def fingerprint(action, operation, actor, action_revision, package_revision):
	return hashlib.sha256(json.dumps([action, operation, actor, int(action_revision), int(package_revision)], separators=(",", ":")).encode()).hexdigest()
