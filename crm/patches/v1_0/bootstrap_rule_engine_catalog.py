"""Bootstrap the default rule catalog on sites upgraded after its DocTypes."""


def execute():
	from crm.fcrm.rule_engine_seed import ensure_active_catalog

	return ensure_active_catalog()
