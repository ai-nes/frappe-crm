"""Controller for the immutable admission event decision DocType."""
from __future__ import annotations

from frappe.model.document import Document


class CRMAdmissionEventDecision(Document):
    """Persistence-only decision record; policy lives in the service layer."""

    pass
