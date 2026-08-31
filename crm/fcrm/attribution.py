"""Student-first read projections for campaign and event evidence.

Contact entry points remain deliberately narrow compatibility adapters. They
never turn a Contact link into authority to read a Student's evidence.
"""

from __future__ import annotations

from collections import defaultdict

import frappe

from crm.fcrm.student_contact_conversion import contacts_for_student, students_for_contact


def _event_campaigns(event_names):
	"""Resolve Event campaigns in one query; missing links stay visible as None."""
	event_names = list({name for name in event_names if name})
	if not event_names:
		return {}
	return {
		row.name: row.crm_campaign
		for row in frappe.db.get_all("CRM Event", filters={"name": ["in", event_names]}, fields=["name", "crm_campaign"])
	}


def _superseded_names(doctype, rows):
	names = [row.name for row in rows]
	if not names:
		return set()
	return set(frappe.db.get_all(doctype, filters={"supersedes": ["in", names]}, pluck="supersedes"))


def _engagement_rows(kind, filters=None, fields=None):
	"""Read the single canonical marketing evidence table."""
	query_filters = dict(filters or {})
	query_filters["engagement_kind"] = kind
	return frappe.db.get_all("CRM Marketing Engagement", filters=query_filters, fields=fields or ["*"])


def _sort_key(touchpoint):
	# Name makes ordering stable for evidence created at the same instant.
	return (str(touchpoint.get("touched_at") or ""), str(touchpoint.get("reference_docname") or ""))


def _touchpoints_for_student(student):
	"""Raw Student evidence, chronologically ordered and including corrections."""
	campaign_rows = frappe.db.get_all("CRM Marketing Engagement", filters={"student": student, "engagement_kind": "campaign_touch"}, fields=["name", "crm_campaign", "touched_at", "source", "supersedes"])
	event_rows = frappe.db.get_all("CRM Marketing Engagement", filters={"student": student, "engagement_kind": "event_participation"}, fields=["name", "crm_event", "registered_at", "status", "supersedes"])
	campaign_superseded = _superseded_names("CRM Marketing Engagement", campaign_rows)
	event_superseded = _superseded_names("CRM Marketing Engagement", event_rows)
	event_campaigns = _event_campaigns(row.crm_event for row in event_rows)
	touchpoints = [
		{
			"touched_at": row.touched_at,
			"campaign": row.crm_campaign,
			"source": "Campaign Touchpoint",
			"reference_doctype": "CRM Marketing Engagement",
			"reference_docname": row.name,
			"superseded": row.name in campaign_superseded,
		}
		for row in campaign_rows
		if row.touched_at
	]
	touchpoints.extend(
		{
			"touched_at": row.registered_at,
			"campaign": event_campaigns.get(row.crm_event) or None,
			"event": row.crm_event,
			"status": row.status,
			"source": "Event Participation",
			"reference_doctype": "CRM Marketing Engagement",
			"reference_docname": row.name,
			"superseded": row.name in event_superseded,
		}
		for row in event_rows
		if row.registered_at
	)
	return sorted(touchpoints, key=_sort_key)


def get_student_touchpoints(student):
	"""All Student evidence, oldest first; unresolved Event campaigns are kept."""
	if not frappe.db.exists("CRM Student", student):
		frappe.throw(f"CRM Student {student} does not exist")
	return _touchpoints_for_student(student)


def _current_touchpoints(student):
	return [row for row in get_student_touchpoints(student) if not row.get("superseded")]


def get_student_first_touch(student):
	touchpoints = _current_touchpoints(student)
	return touchpoints[0] if touchpoints else None


def get_student_last_touch(student):
	touchpoints = _current_touchpoints(student)
	return touchpoints[-1] if touchpoints else None


def get_student_multi_touch_attribution(student):
	"""Equal-credit projection across active, campaign-resolvable evidence."""
	touchpoints = [row for row in _current_touchpoints(student) if row.get("campaign")]
	if not touchpoints:
		return {}
	credit = 1.0 / len(touchpoints)
	result = defaultdict(float)
	for row in touchpoints:
		result[row["campaign"]] += credit
	return dict(result)


def get_student_attribution(student):
	"""Bounded Student projection used by Student context and compatibility APIs."""
	timeline = get_student_touchpoints(student)
	current = [row for row in timeline if not row.get("superseded")]
	creditable = [row for row in current if row.get("campaign")]
	credit = defaultdict(float)
	if creditable:
		for row in creditable:
			credit[row["campaign"]] += 1.0 / len(creditable)
	return {
		"firstTouch": current[0] if current else None,
		"lastTouch": current[-1] if current else None,
		"multiTouch": dict(credit),
		"touchpoints": timeline,
	}


def get_last_touch_campaign_by_student(students=None):
	"""Student last-touch map, with batched Event campaign resolution.

	When a cohort is supplied, constrain both evidence reads to that bounded
	set.  This keeps dashboard attribution aligned with the dashboard's existing
	Contact-derived scope while retaining a Student-first projection.
	"""
	student_filter = {"student": ["in", list(set(students or []))]} if students is not None else None
	if students is not None and not students:
		return {}
	touchpoints = []
	campaign_rows = _engagement_rows("campaign_touch", student_filter, ["name", "student", "crm_campaign", "touched_at"])
	campaign_superseded = _superseded_names("CRM Marketing Engagement", campaign_rows)
	for row in campaign_rows:
		if row.student and row.touched_at and row.name not in campaign_superseded:
			touchpoints.append({"student": row.student, "campaign": row.crm_campaign, "touched_at": row.touched_at, "name": row.name})
	events = _engagement_rows("event_participation", student_filter, ["name", "student", "crm_event", "registered_at"])
	event_superseded = _superseded_names("CRM Marketing Engagement", events)
	campaigns = _event_campaigns(row.crm_event for row in events)
	for row in events:
		if row.student and row.registered_at and row.name not in event_superseded:
			touchpoints.append({"student": row.student, "campaign": campaigns.get(row.crm_event), "touched_at": row.registered_at, "name": row.name})
	last = {}
	for row in touchpoints:
		if not row["campaign"]:
			continue
		if row["student"] not in last or (str(row["touched_at"]), row["name"]) > (str(last[row["student"]]["touched_at"]), last[row["student"]]["name"]):
			last[row["student"]] = row
	return {student: row["campaign"] for student, row in last.items()}


def get_equal_credit_by_campaign_for_students(students):
	"""Batch equal-credit rollup for a bounded Student cohort (no N+1 reads)."""
	students = list(set(students or []))
	if not students:
		return {}
	campaign_rows = _engagement_rows("campaign_touch", {"student": ["in", students]}, ["name", "student", "crm_campaign", "touched_at"])
	event_rows = _engagement_rows("event_participation", {"student": ["in", students]}, ["name", "student", "crm_event", "registered_at"])
	campaign_superseded = _superseded_names("CRM Marketing Engagement", campaign_rows)
	event_superseded = _superseded_names("CRM Marketing Engagement", event_rows)
	event_campaigns = _event_campaigns(row.crm_event for row in event_rows)
	by_student = defaultdict(list)
	for row in campaign_rows:
		if row.name not in campaign_superseded and row.crm_campaign and row.touched_at:
			by_student[row.student].append(row.crm_campaign)
	for row in event_rows:
		campaign = event_campaigns.get(row.crm_event) or None
		if row.name not in event_superseded and campaign and row.registered_at:
			by_student[row.student].append(campaign)
	rollup = defaultdict(float)
	for campaigns in by_student.values():
		for campaign in campaigns:
			rollup[campaign] += 1.0 / len(campaigns)
	return dict(rollup)


def get_campaign_progression_rollups():
	"""Student lifecycle counts bucketed by deterministic last-touch campaign."""
	students_by_campaign = defaultdict(set)
	for student, campaign in get_last_touch_campaign_by_student().items():
		students_by_campaign[campaign].add(student)
	all_students = {student for values in students_by_campaign.values() for student in values}
	stages = {
		row.name: (row.lifecycle_stage or row.enrollment_status or "Lead")
		for row in frappe.db.get_all("CRM Student", filters={"name": ["in", list(all_students) or ["__none__"]]}, fields=["name", "lifecycle_stage", "enrollment_status"])
	}
	rollups = {}
	for campaign, students in students_by_campaign.items():
		counts = {"students": len(students), "lead": 0, "mql": 0, "applicant": 0, "enrolled": 0, "lost": 0}
		for student in students:
			stage = str(stages.get(student) or "lead").casefold()
			if "mql" in stage:
				counts["mql"] += 1
			elif "applicant" in stage or "hồ sơ" in stage:
				counts["applicant"] += 1
			elif "enroll" in stage or "nhập học" in stage:
				counts["enrolled"] += 1
			elif "lost" in stage or "không" in stage:
				counts["lost"] += 1
			else:
				counts["lead"] += 1
		rollups[campaign] = counts
	return rollups


def _student_for_contact(contact):
	if not frappe.db.exists("CRM Contact", contact):
		frappe.throw(f"CRM Contact {contact} does not exist")
	students = students_for_contact(contact)
	if len(students) != 1:
		return None
	student = students[0]
	if not frappe.db.exists("CRM Student", student):
		return None
	doc = frappe.get_doc("CRM Student", student)
	if not doc.has_permission("read"):
		frappe.throw("You do not have permission to view this Student.", frappe.PermissionError)
	return student


def _touchpoints_for_contact(contact):
	"""Read canonical marketing evidence for a Contact projection."""
	campaign_rows = _engagement_rows("campaign_touch", {"crm_contact": contact}, ["name", "crm_campaign", "touched_at", "source", "supersedes"])
	event_rows = _engagement_rows("event_participation", {"crm_contact": contact}, ["name", "crm_event", "registered_at", "status", "supersedes"])
	campaign_superseded = _superseded_names("CRM Marketing Engagement", campaign_rows)
	event_superseded = _superseded_names("CRM Marketing Engagement", event_rows)
	event_campaigns = _event_campaigns(row.crm_event for row in event_rows)
	touchpoints = [
		{
			"touched_at": row.touched_at,
			"campaign": row.crm_campaign,
			"source": row.source or "Campaign Touchpoint",
			"reference_doctype": "CRM Marketing Engagement",
			"reference_docname": row.name,
			"superseded": row.name in campaign_superseded,
		}
		for row in campaign_rows
		if row.touched_at
	]
	touchpoints.extend(
		{
			"touched_at": row.registered_at,
			"campaign": event_campaigns.get(row.crm_event) or None,
			"event": row.crm_event,
			"status": row.status,
			"source": "Event Participation",
			"reference_doctype": "CRM Marketing Engagement",
			"reference_docname": row.name,
			"superseded": row.name in event_superseded,
		}
		for row in event_rows
		if row.registered_at
	)
	return sorted(touchpoints, key=_sort_key)


# Contact compatibility adapters: linked Students use the canonical projection.
def get_contact_touchpoints(crm_contact):
	students = students_for_contact(crm_contact)
	if students:
		touchpoints = []
		for student in students:
			if not frappe.db.exists("CRM Student", student):
				continue
			doc = frappe.get_doc("CRM Student", student)
			if not doc.has_permission("read"):
				continue
			touchpoints.extend(get_student_touchpoints(student))
		if touchpoints:
			return sorted(touchpoints, key=_sort_key)
	return _touchpoints_for_contact(crm_contact)


def get_first_touch(crm_contact):
	touchpoints = [row for row in get_contact_touchpoints(crm_contact) if not row.get("superseded")]
	return touchpoints[0] if touchpoints else None


def get_last_touch(crm_contact):
	touchpoints = [row for row in get_contact_touchpoints(crm_contact) if not row.get("superseded")]
	return touchpoints[-1] if touchpoints else None


def get_multi_touch_attribution(crm_contact):
	students = students_for_contact(crm_contact)
	if students:
		credit = defaultdict(float)
		for student in students:
			for campaign, value in get_student_multi_touch_attribution(student).items():
				credit[campaign] += value
		if credit:
			return dict(credit)
	touchpoints = [row for row in _touchpoints_for_contact(crm_contact) if not row.get("superseded") and row.get("campaign")]
	if not touchpoints:
		return {}
	credit = 1.0 / len(touchpoints)
	result = defaultdict(float)
	for row in touchpoints:
		result[row["campaign"]] += credit
	return dict(result)


def get_last_touch_campaign_by_contact():
	"""Compatibility map spanning linked Students and canonical evidence."""
	student_campaigns = get_last_touch_campaign_by_student()
	result = {}
	for student, campaign in student_campaigns.items():
		for contact in contacts_for_student(student):
			result[contact] = campaign
	canonical_contacts = set(frappe.db.get_all("CRM Marketing Engagement", pluck="crm_contact"))
	for contact in canonical_contacts:
		if not contact or contact in result:
			continue
		last = get_last_touch(contact)
		if last and last.get("campaign"):
			result[contact] = last["campaign"]
	return result


def get_campaign_names_by_last_touch(campaign):
	return {contact for contact, value in get_last_touch_campaign_by_contact().items() if value == campaign}


@frappe.whitelist()
def get_contact_attribution(contact):
	if not frappe.db.exists("CRM Contact", contact):
		frappe.throw(f"CRM Contact {contact} does not exist")
	students = students_for_contact(contact)
	if len(students) == 1:
		projection = get_student_attribution(students[0])
		if projection["touchpoints"]:
			return projection
	timeline = get_contact_touchpoints(contact)
	current = [row for row in timeline if not row.get("superseded")]
	creditable = [row for row in current if row.get("campaign")]
	credit = defaultdict(float)
	for row in creditable:
		credit[row["campaign"]] += 1.0 / len(creditable)
	return {"firstTouch": current[0] if current else None, "lastTouch": current[-1] if current else None, "multiTouch": dict(credit), "touchpoints": timeline}
