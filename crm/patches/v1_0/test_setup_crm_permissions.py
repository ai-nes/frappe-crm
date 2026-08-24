from crm.patches.v1_0.setup_crm_permissions import _merge_duplicate_permissions


def test_duplicate_canonical_roles_keep_only_common_permissions():
	perms = [
		{"role": "Marketing", "read": 1, "write": 1},
		{"role": "Marketing", "read": 1, "create": 1},
		{"role": "Lead Sales", "read": 1, "write": 1},
	]
	by_role = {permission["role"]: permission for permission in _merge_duplicate_permissions(perms)}

	assert by_role["Marketing"] == {"role": "Marketing", "read": 1}
	assert by_role["Lead Sales"] == {"role": "Lead Sales", "read": 1, "write": 1}
