"""Canonical digest helpers for the NBA control-plane contracts.

Pure module -- no Frappe import -- so the digest rules can be exercised in
isolation and stay byte-identical to the consumer side. The canonical form is
compact, key-sorted, ASCII-escaped JSON; a value that is not JSON-serialisable
raises instead of being silently coerced.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import time, timedelta
from typing import Any


def canonical_digest(value: Any) -> str:
	"""Return the SHA-256 of the canonical JSON encoding of ``value``.

	The encoding sorts object keys, drops insignificant whitespace and escapes
	non-ASCII characters. No ``default`` hook is used: a value that ``json`` can
	not serialise raises ``TypeError`` rather than being coerced to a string.
	"""
	body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
	return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _as_bool(value: Any) -> bool:
	if isinstance(value, str):
		return value.strip().lower() in {"1", "true", "yes", "on"}
	return bool(value)


def _actor_list(value: Any) -> list[str]:
	"""Parse an ``allowed_actors`` cell into a sorted list of role names."""
	if value in (None, ""):
		return []
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except json.JSONDecodeError:
			value = [part.strip() for part in value.split(",")]
	if isinstance(value, Mapping):
		value = list(value.keys())
	if not isinstance(value, (list, tuple, set)):
		raise ValueError("allowed_actors must be a list, mapping or comma string.")
	return sorted({str(item).strip() for item in value if str(item).strip()})


def _text(value: Any) -> str | None:
	if value in (None, ""):
		return None
	return str(value)


def time_text(value: Any) -> str | None:
	"""Normalise a clock value to zero-padded ``HH:MM:SS``.

	MariaDB ``time`` columns surface as ``datetime.timedelta`` through the ORM;
	``str(timedelta(hours=9))`` is ``"9:00:00"`` which neither sorts nor parses
	like an ISO time, so every reader here must go through this helper.
	"""
	if value in (None, ""):
		return None
	if isinstance(value, timedelta):
		total = int(value.total_seconds())
		return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"
	if isinstance(value, time):
		return value.replace(microsecond=0).isoformat()
	text = str(value).split(".", 1)[0]
	parts = text.split(":")
	if len(parts) == 3 and all(p.isdigit() for p in parts):
		return ":".join(f"{int(p):02d}" for p in parts)
	return text


def json_string_list(value: Any) -> list[str]:
	"""Coerce a JSON-array cell (list, ``"[...]"`` string, or CSV) to a sorted, de-duped list."""
	if value in (None, ""):
		return []
	if isinstance(value, str):
		try:
			parsed = json.loads(value)
		except json.JSONDecodeError:
			parsed = [part.strip() for part in value.split(",")]
		value = parsed
	if isinstance(value, Mapping):
		value = list(value.keys())
	if not isinstance(value, (list, tuple, set)):
		raise ValueError("value must be a JSON array, list or comma string.")
	return sorted({str(item).strip() for item in value if str(item).strip()})


def action_definition_snapshot(row: Mapping[str, Any]) -> dict:
	"""Bounded, canonical view of an Action's policy-relevant definition fields.

	This dict -- and only this dict -- is what gets digested for an Action's
	``definition_digest``; keys are fixed and ordering is deterministic.
	"""
	category = row.get("category") or row.get("action_type")
	academic_constraint = row.get("academic_constraint")
	if isinstance(academic_constraint, str):
		try:
			academic_constraint = json.loads(academic_constraint)
		except json.JSONDecodeError:
			academic_constraint = {}
	if not isinstance(academic_constraint, Mapping):
		academic_constraint = {}
	return {
		"code": _text(row.get("code")),
		"display_name": _text(row.get("display_name")),
		"category": _text(category),
		"need": _text(row.get("need")),
		"purpose": _text(row.get("purpose")),
		"default_channel": _text(row.get("default_channel")) or "NONE",
		"allowed_actors": _actor_list(row.get("allowed_actors")),
		"requires_approval": _as_bool(row.get("requires_approval")),
		"requires_parent_authority": _as_bool(row.get("requires_parent_authority")),
		"academic_constraint": dict(academic_constraint),
		"auto_execute": _as_bool(row.get("auto_execute")),
		"enabled": _as_bool(row.get("enabled")),
	}


def timing_policy_snapshot(row: Mapping[str, Any]) -> dict:
	"""Bounded, canonical view of a Timing Policy's schedule-shaping fields."""
	return {
		"trigger_type": _text(row.get("trigger_type")) or "relative",
		"delay_value": float(row.get("delay_value") or 0),
		"delay_unit": _text(row.get("delay_unit")) or "hours",
		"allowed_start_time": time_text(row.get("allowed_start_time")),
		"allowed_end_time": time_text(row.get("allowed_end_time")),
		"deadline_type": _text(row.get("deadline_type")) or "none",
		"deadline_offset": float(row.get("deadline_offset") or 0),
		"recurrence_type": _text(row.get("recurrence_type")) or "none",
		"recurrence_interval": int(row.get("recurrence_interval") or 1),
	}
