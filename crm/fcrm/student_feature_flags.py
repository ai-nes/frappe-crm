"""Independent Phase 4 rollout gates (all disabled unless explicitly enabled)."""

import frappe


def enabled(feature: str) -> bool:
	return bool(getattr(frappe, "conf", {}).get(f"crm_student_{feature}_enabled", False))

