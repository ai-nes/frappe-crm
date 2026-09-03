"""Provider boundary for governed Action Attempts.

The default adapter is deliberately disabled. Deployments must register a provider
implementation explicitly; Workbench never falls back to browser-side sending.
"""

from __future__ import annotations

from collections.abc import Callable


ProviderSender = Callable[[str, str], str]
_senders: dict[str, ProviderSender] = {}


def register_provider(channel: str, sender: ProviderSender) -> None:
	if channel not in {"EMAIL", "MESSAGE", "CALL"}:
		raise ValueError("Unsupported Action provider channel")
	_senders[channel] = sender


def send(channel: str, provider_idempotency_key: str, attempt_id: str) -> str:
	sender = _senders.get(channel)
	if sender is None:
		raise RuntimeError("No governed Action provider is configured")
	return sender(provider_idempotency_key, attempt_id)
