"""Bench-callable wrapper for the direct canonical role cutover command."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cutover_canonical_roles.py"
_SPEC = importlib.util.spec_from_file_location("crm_canonical_role_cutover", _SCRIPT)
if _SPEC is None or _SPEC.loader is None:
	raise ImportError(f"Cannot load role cutover script: {_SCRIPT}")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

execute = _MODULE.execute
verify = _MODULE.verify
