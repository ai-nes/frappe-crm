from crm.patches.v1_0.setup_crm_permissions import _expand_profile_permission_aliases


def test_profile_permission_aliases_copy_existing_grants_only():
	perms = [{"role": "Promoter-PR", "read": 1}, {"role": "Team Leader", "read": 1, "write": 1}]
	expanded = _expand_profile_permission_aliases(perms)
	by_role = {permission["role"]: permission for permission in expanded}

	assert by_role["Marketing"] == {"role": "Marketing", "read": 1}
	assert by_role["Lead Sales"] == {"role": "Lead Sales", "read": 1, "write": 1}
