import frappe
from frappe.model.document import Document

from crm.fcrm.scoring_policy import bump_active_templates_for_signal


class CRMScoreSignal(Document):
	def on_update(self):
		bump_active_templates_for_signal(self.name)

	def on_trash(self):
		# Deleting a signal drops every rule referencing it from the resolved
		# policy (resolve_policy_rules skips unresolved signals) -- every
		# Active template that referenced it must still re-version so
		# crm-agents observes the change, exactly as a content edit would.
		# Deferred past commit: on_trash fires before the row is actually gone,
		# so resolving now would still see (and hash in) this signal's content.
		frappe.enqueue(
			"crm.fcrm.scoring_policy.bump_active_templates_for_signal",
			queue="short",
			enqueue_after_commit=True,
			signal_name=self.name,
		)
