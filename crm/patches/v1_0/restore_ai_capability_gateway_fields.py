"""Repair the capability gateway schema if the original one-shot patch drifted."""

from crm.patches.v1_0.add_ai_capability_gateway_fields import ensure_ai_capability_gateway_fields


def execute():
	ensure_ai_capability_gateway_fields()
