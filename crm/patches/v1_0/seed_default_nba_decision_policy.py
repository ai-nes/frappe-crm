"""Ensure a fresh site has the canonical active NBA decision policy."""

from crm.fcrm.nba_policy import ensure_default_decision_policy


def execute():
	ensure_default_decision_policy()
