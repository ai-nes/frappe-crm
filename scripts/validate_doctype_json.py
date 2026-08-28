"""Validate DocType JSON before handing schema work to Frappe."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
	files = sorted(Path("crm").rglob("*.json"))
	invalid = []
	for path in files:
		try:
			json.loads(path.read_text(encoding="utf-8"))
		except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
			invalid.append(f"{path}: {error}")

	if invalid:
		print("Invalid CRM JSON files:")
		print("\n".join(invalid))
		return 1

	print(f"Validated {len(files)} CRM JSON files.")
	return 0


if __name__ == "__main__":
	sys.exit(main())
