import frappe

PURPOSE_TEMPLATES = {
	"Follow-up after counseling": {
		"subject": "Following up on your recent counseling session",
		"body": (
			"Hi {name},\n\n"
			"Thank you for taking the time to speak with us recently. I wanted to follow up and "
			"see if you had any further questions about the programs we discussed.\n\n"
			"Feel free to reply here or let me know a good time to connect."
		),
	},
	"Scholarship information": {
		"subject": "Scholarship opportunities for you",
		"body": (
			"Hi {name},\n\n"
			"I wanted to share some scholarship opportunities that may be relevant to your "
			"application. Let me know if you'd like more details on eligibility and deadlines."
		),
	},
	"Tuition information": {
		"subject": "Tuition details you requested",
		"body": (
			"Hi {name},\n\n"
			"Here is an overview of tuition and fee information for the program you're "
			"interested in. Happy to walk through the breakdown together if helpful."
		),
	},
	"Application reminder": {
		"subject": "A quick reminder about your application",
		"body": (
			"Hi {name},\n\n"
			"Just a friendly reminder that your application is still in progress. Let me know "
			"if there's anything holding you up and I'll help however I can."
		),
	},
	"Missing document reminder": {
		"subject": "A document is still needed for your application",
		"body": (
			"Hi {name},\n\n"
			"We're missing a document to complete your application file. Could you send it "
			"over when you get a chance? Happy to clarify what's needed."
		),
	},
	"Event invitation": {
		"subject": "You're invited",
		"body": (
			"Hi {name},\n\n"
			"We'd love to have you join an upcoming event. It's a great chance to learn more "
			"and get your questions answered in person."
		),
	},
	"Dormitory information": {
		"subject": "Dormitory and housing information",
		"body": (
			"Hi {name},\n\n"
			"Here's some information about on-campus housing options. Let me know if you'd "
			"like help comparing rooms or the application timeline."
		),
	},
	"Career information": {
		"subject": "Career outcomes and opportunities",
		"body": (
			"Hi {name},\n\n"
			"I wanted to share some information about career outcomes and opportunities "
			"connected to this program. Happy to go deeper on any part of it."
		),
	},
	"Re-engagement": {
		"subject": "Checking back in",
		"body": (
			"Hi {name},\n\n"
			"It's been a little while since we last connected. I wanted to check in and see "
			"if you still have questions I can help with."
		),
	},
	"Custom": {
		"subject": "A note for you",
		"body": ("Hi {name},\n\n"),
	},
}

DEFAULT_TEMPLATE = PURPOSE_TEMPLATES["Custom"]


def _safe_insight_summary(ai_insight: str | None) -> str | None:
	if not ai_insight:
		return None
	try:
		summary = frappe.db.get_value("CRM AI Student Insight", ai_insight, "summary")
	except Exception:
		return None
	if not summary or not isinstance(summary, str):
		return None
	return summary.strip()


def generate_mock_draft(
	contact_name: str,
	purpose: str,
	instruction: str | None = None,
	ai_insight: str | None = None,
) -> tuple[str, str]:
	"""Mock (non-LLM) draft generator. Returns (subject, body).

	Placeholder for the real crm-agents-backed generator; keep this return
	contract (subject, body strings only) stable so a future provider can
	swap in without touching callers.
	"""
	contact_full_name = frappe.db.get_value("CRM Student", contact_name, "full_name") or contact_name

	template = PURPOSE_TEMPLATES.get(purpose, DEFAULT_TEMPLATE)
	subject = template["subject"]
	body = template["body"].format(name=contact_full_name)

	insight_summary = _safe_insight_summary(ai_insight)
	if insight_summary:
		body += f"\n\nFor context, here's a quick summary from our notes: {insight_summary}"

	if instruction:
		body += f"\n\n(Rep instruction considered: {instruction.strip()})"

	body += "\n\nBest,\n"

	return subject, body


def get_provider():
	return frappe.conf.get("ai_email_draft_provider", "mock")
