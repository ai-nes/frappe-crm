from unittest import TestCase
from unittest.mock import patch

import frappe

from crm.fcrm import lead_routing_policy


def _policy(order=("campaign", "group", "global"), *, enabled=True):
	return {
		"enabled": enabled,
		"layers": [
			{"key": key, "enabled": True, "priority": index + 1}
			for index, key in enumerate(order)
		],
		"distributionStrategy": "least_load",
		"capacityRequired": True,
		"version": "lead-routing-v7",
	}


class TestLeadRoutingPolicy(TestCase):
	def test_legacy_control_row_uses_enabled_layer_defaults(self):
		policy = lead_routing_policy.get_lead_routing_policy(
			{
				"routing_enabled": 1,
				"lead_campaign_layer_enabled": 0,
				"lead_group_layer_enabled": 0,
				"lead_global_layer_enabled": 0,
				"lead_layer_order": "",
				"lead_distribution_strategy": "",
			}
		)

		self.assertEqual([layer["enabled"] for layer in policy["layers"]], [True, True, True])

	def test_explicit_policy_can_disable_layers(self):
		policy = lead_routing_policy.get_lead_routing_policy(
			{
				"routing_enabled": 1,
				"lead_campaign_layer_enabled": 0,
				"lead_group_layer_enabled": 1,
				"lead_global_layer_enabled": 0,
				"lead_layer_order": "group,campaign,global",
				"lead_distribution_strategy": "least_load",
			}
		)

		self.assertEqual(policy["layerOrder"], ["group", "campaign", "global"])
		self.assertEqual([layer["enabled"] for layer in policy["layers"]], [True, False, False])

	def test_campaign_scope_has_priority_over_group_and_global(self):
		campaign_teams = [{"name": "TEAM-CAMPAIGN", "team_name": "Campaign Team"}]
		recipient = {"team": "TEAM-CAMPAIGN", "ownerStaff": "STAFF-1"}
		with (
			patch.object(
				lead_routing_policy,
				"_campaign_scope",
				return_value=(campaign_teams, "CAMPAIGN:CAMP-1"),
			),
			patch.object(
				lead_routing_policy,
				"_active_teams_for_province",
				side_effect=AssertionError("group layer must not run after campaign match"),
			),
			patch.object(
				lead_routing_policy,
				"select_recipient_for_teams",
				return_value=recipient,
			) as select,
		):
			result = lead_routing_policy.resolve_lead_recipient(
				{"campaign": "CAMP-1", "branch": "CAMPUS-1"},
				policy=_policy(),
				province="Province 1",
				campus="CAMPUS-1",
			)

		self.assertIs(result, recipient)
		self.assertEqual(select.call_args.kwargs["scope_key"], "CAMPAIGN:CAMP-1")

	def test_group_scope_does_not_fall_to_global_when_team_is_unavailable(self):
		with (
			patch.object(lead_routing_policy, "_active_teams_for_province", return_value=[]),
			patch.object(
				lead_routing_policy,
				"_active_teams_for_campus",
				side_effect=AssertionError("matched group scope must not fall to global"),
			),
		):
			with self.assertRaises(frappe.ValidationError) as context:
				lead_routing_policy.resolve_lead_recipient(
					{"branch": "CAMPUS-1"},
					policy=_policy(),
					province="Province 1",
					campus="CAMPUS-1",
				)

		self.assertEqual(context.exception.code, "GROUP_TARGET_UNAVAILABLE")

	def test_global_scope_can_route_a_lead_without_province(self):
		recipient = {"team": "TEAM-GLOBAL", "ownerStaff": "STAFF-2"}
		with (
			patch.object(
				lead_routing_policy,
				"_active_teams_for_campus",
				return_value=[{"name": "TEAM-GLOBAL", "team_name": "Campus Team"}],
			),
			patch.object(
				lead_routing_policy,
				"select_recipient_for_teams",
				return_value=recipient,
			) as select,
		):
			result = lead_routing_policy.resolve_lead_recipient(
				{"branch": "CAMPUS-1"},
				policy=_policy(),
				province=None,
				campus="CAMPUS-1",
			)

		self.assertIs(result, recipient)
		self.assertEqual(select.call_args.kwargs["scope_key"], "GLOBAL:CAMPUS-1")

	def test_disabled_policy_is_explicitly_blocked(self):
		with self.assertRaises(frappe.ValidationError) as context:
			lead_routing_policy.resolve_lead_recipient(
				{"branch": "CAMPUS-1"},
				policy=_policy(enabled=False),
				campus="CAMPUS-1",
			)

		self.assertEqual(context.exception.code, "LEAD_ROUTING_DISABLED")
