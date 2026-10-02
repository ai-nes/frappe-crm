from unittest import TestCase
from unittest.mock import patch

import frappe

from crm.fcrm import lead_processing, lead_routing_policy


def _policy(order=("campaign", "group", "global"), *, enabled=True):
	return {
		"enabled": enabled,
		"layers": [{"key": key, "enabled": True, "priority": index + 1} for index, key in enumerate(order)],
		"distributionStrategy": "least_load",
		"capacityRequired": True,
		"version": "lead-routing-v7",
	}


class TestLeadRoutingPolicy(TestCase):
	def test_company_assignment_validates_active_team_and_member_without_geography(self):
		with (
			patch.object(
				frappe.db,
				"get_value",
				side_effect=[
					frappe._dict(is_active=1, team_type="Sales"),
					frappe._dict(name="SALE-1", is_active=1, user="sale@example.com"),
					1,
				],
			),
			patch.object(frappe, "get_roles", return_value=["Sale"]),
			patch.object(lead_processing, "resolve_crm_profile", return_value="sales"),
			patch.object(
				lead_processing,
				"_active_memberships",
				return_value=[frappe._dict(staff="SALE-1", function="Sale")],
			),
			patch.object(lead_processing, "team_routing_readiness") as geography,
		):
			lead_processing._validate_lead_ownership_target(
				{"province": "OTHER-PROVINCE"},
				"SALE-1",
				"TEAM-1",
				allow_cross_province=True,
			)
		geography.assert_not_called()

	def test_company_mode_ignores_campus_province_and_batch_team(self):
		policy = {**_policy(), "routingMode": "global", "distributionStrategy": "round_robin"}
		teams = [{"name": "TEAM-OTHER-CAMPUS"}]
		with (
			patch.object(lead_routing_policy, "_active_teams_for_company", return_value=teams) as company,
			patch.object(lead_routing_policy, "_campaign_scope") as campaign,
			patch.object(lead_routing_policy, "select_recipient_for_teams", return_value={}) as select,
		):
			lead_routing_policy.resolve_lead_recipient(
				{"branch": "CAMPUS-1"},
				policy=policy,
				province="PROVINCE-1",
				team_id="TEAM-1",
			)
		company.assert_called_once_with()
		campaign.assert_not_called()
		self.assertEqual(select.call_args.args[0], teams)
		self.assertEqual(select.call_args.kwargs["scope_key"], "GLOBAL:COMPANY")

	def test_team_mode_selects_only_configured_team_without_campus_boundary(self):
		policy = {**_policy(), "routingMode": "group", "provinceTeamPriority": {"PROVINCE-1": "TEAM-2"}}
		with (
			patch.object(
				lead_routing_policy, "_active_teams_for_province", return_value=[{"name": "TEAM-2"}]
			) as teams,
			patch.object(lead_routing_policy, "select_recipient_for_teams", return_value={}),
		):
			lead_routing_policy.resolve_lead_recipient(
				{"branch": "CAMPUS-1"}, policy=policy, province="PROVINCE-1"
			)
		teams.assert_called_once_with("PROVINCE-1", campus=None, team_id="TEAM-2")

	def test_selected_modes_never_fallback_when_configuration_is_missing(self):
		for mode, code in [
			("group", "PROVINCE_TEAM_NOT_CONFIGURED"),
			("campaign", "CAMPAIGN_MAPPING_INVALID"),
		]:
			with (
				self.subTest(mode=mode),
				patch.object(lead_routing_policy, "_campaign_scope", return_value=None),
				patch.object(lead_routing_policy, "_active_teams_for_company") as company,
			):
				with self.assertRaises(frappe.ValidationError) as error:
					lead_routing_policy.resolve_lead_recipient(
						{"branch": "CAMPUS-1"},
						policy={**_policy(), "routingMode": mode},
						province="PROVINCE-1",
					)
				self.assertEqual(error.exception.code, code)
				company.assert_not_called()

	def test_priority_validation_rejects_team_from_another_province(self):
		with (
			patch.object(frappe.db, "exists", return_value=True),
			patch.object(lead_routing_policy, "_active_teams_for_province", return_value=[]),
		):
			with self.assertRaises(frappe.ValidationError):
				lead_routing_policy.validate_policy_payload(
					province_team_priority={"PROVINCE-1": "TEAM-WRONG"}
				)

	def test_valid_mode_normalizes_distribution_to_round_robin(self):
		values = lead_routing_policy.validate_policy_payload(
			routing_mode="global", distribution_strategy="least_load"
		)
		self.assertEqual(values["lead_distribution_strategy"], "round_robin")
		with self.assertRaises(frappe.ValidationError):
			lead_routing_policy.validate_policy_payload(routing_mode="unknown")

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
