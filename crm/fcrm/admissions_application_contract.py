"""Framework-independent application command contract helpers."""

from __future__ import annotations

from typing import Any


def application_projection(values: dict[str, Any]) -> dict[str, Any]:
	"""Return only current-state Student fields allowed from an Application."""

	return {
		field: values[field]
		for field in ("major", "campus", "admission_year", "admission_method")
		if values.get(field) not in (None, "")
	}
