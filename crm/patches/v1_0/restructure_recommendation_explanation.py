"""Additive structured-explanation column on ``CRM Recommendation``.

Adds ``explanation`` (a JSON object carrying the grounded, structured
explanation on the NBA boundary -- WHAT + WHY + WHY NOW + EVIDENCE +
UNCERTAINTY + WHEN: ``action`` (``code``, ``title``), ``summary``,
``why_action``, ``why_now``, ``evidence`` (a list of ``summary`` +
``evidence_ref`` objects), ``uncertainty``, and ``timing`` (``recommended_at``,
``reason``). It carries no execution-content field -- message copy, CTAs,
retry/channel-switch guidance belong to a Template / Sales Playbook / a
future NBA Evaluation, not this Recommendation. This supersedes the
plain-string ``rationale_vi`` shipped previously; ``rationale_vi``
and ``rationale_source`` are left in place, unused, since dropping columns is
out of scope for an additive-only pass -- ``rationale_source`` is reused for
provenance of the new ``explanation`` field. The new column is introduced
empty -- the explanation pass is a post-commit, best-effort step, so there is
no backfill. Write-once semantics for ``explanation`` are enforced in the
doctype controller and by the fenced ``set_recommendation_rationale`` command,
not at the schema level. Idempotent: the column change is guarded on
``information_schema``.

Rollback:
  ``ALTER TABLE `tabCRM Recommendation` DROP COLUMN explanation;``
"""

import frappe

_TABLE = "tabCRM Recommendation"
_COLUMNS = {
	"explanation": "longtext NULL",
}


def execute():
	if not frappe.db.table_exists("CRM Recommendation"):
		return

	frappe.reload_doc("fcrm", "doctype", "crm_recommendation")
	_add_columns(_TABLE, _COLUMNS)

	if not frappe.flags.in_test:
		frappe.db.commit()


def _add_columns(table: str, columns: dict[str, str]) -> None:
	for name, ddl in columns.items():
		if not _column_exists(table, name):
			frappe.db.sql_ddl(f"ALTER TABLE `{table}` ADD COLUMN `{name}` {ddl}")


def _column_exists(table: str, column: str) -> bool:
	return bool(
		frappe.db.sql(
			"SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() "
			"AND table_name = %s AND column_name = %s LIMIT 1",
			(table, column),
		)
	)
