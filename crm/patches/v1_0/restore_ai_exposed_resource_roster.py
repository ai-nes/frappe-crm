"""Repair the AI exposure roster for sites that ran the seed before CRM doctypes existed.

The original gateway-field patch is one-shot.  On an existing site it could
run before the CRM DocType records were installed, leaving every resource at
the default ``custom_ai_exposed = 0`` forever.  Re-running the idempotent seed
after all app patches makes the published roster deterministic while retaining
the explicit dark state for the staged Student/Intent/Interaction resources.
"""

from crm.patches.v1_0.add_ai_capability_gateway_fields import _seed_exposed_crm_doctypes


def execute():
	_seed_exposed_crm_doctypes()
