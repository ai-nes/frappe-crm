from datetime import timedelta

import frappe
from frappe.model.db_query import DatabaseQuery
from frappe.utils import add_days, get_first_day, get_last_day, now_datetime, nowdate

from crm.api._ai_staleness import ai_field_or_unavailable, ai_staleness_threshold_seconds
from crm.api.admissions_dashboard_auth import check_dashboard_access
from crm.fcrm.attribution import (
	get_equal_credit_by_campaign_for_students,
	get_last_touch_campaign_by_student,
)
from crm.fcrm.student_contact_conversion import students_for_contact


def _insight_scope_sql():
	"""Apply the current session's row scope to the AI insight aggregate."""
	condition = DatabaseQuery("CRM AI Lead Insight", user=frappe.session.user).build_match_conditions(
		as_condition=True
	)
	if not condition:
		return "", ()
	return f"AND ({condition.replace('`tabCRM AI Lead Insight`', 'insight')})", ()


def _normalize_date_range(from_date=None, to_date=None):
	if not from_date or not to_date:
		from_date = get_first_day(from_date or nowdate())
		to_date = get_last_day(to_date or nowdate())
	return str(from_date), str(to_date)


def _get_delta(current, previous):
	if not previous:
		return 0.0
	return round(((current - previous) / previous) * 100.0, 1)


def _staff_names_in_sales_team(team):
	"""CRM Staff names with a CRM Team Membership for `team`, or the sentinel
	"__none__" (never a real doc name) when the team has no staff -- shared by
	every dashboard that scopes CRM Contact.assigned_to by team, so the scoping
	logic can't silently diverge between them."""
	staff_names = frappe.db.get_all(
		"CRM Team Membership",
		filters={"parenttype": "CRM Staff", "team": team},
		pluck="parent",
	)
	return staff_names or ["__none__"]


@frappe.whitelist()
def get_sales_dashboard(
	from_date=None,
	to_date=None,
	user=None,
	sales_team=None,
	campus=None,
	admission_term=None,
	section="overview",
):
	# The public API is always authorized and scoped as the authenticated session
	# user. A caller-supplied ``user`` must never select a different role/campus.
	check_dashboard_access("sale")
	from_date, to_date = _normalize_date_range(from_date, to_date)
	diff = frappe.utils.date_diff(to_date, from_date) or 1
	prev_from_date = str(add_days(from_date, -diff))
	to_date_plus_1 = str(add_days(to_date, 1))

	# Base filters for CRM Contact
	base_filters = [
		["creation", ">=", from_date],
		["creation", "<", to_date_plus_1],
		["is_test_record", "=", 0],
	]
	prev_filters = [
		["creation", ">=", prev_from_date],
		["creation", "<", from_date],
		["is_test_record", "=", 0],
	]

	if sales_team:
		staff_in_team = _staff_names_in_sales_team(sales_team)
		base_filters.append(["assigned_to", "in", staff_in_team])
		prev_filters.append(["assigned_to", "in", staff_in_team])

	if campus:
		base_filters.append(["branch", "=", campus])
		prev_filters.append(["branch", "=", campus])
	if admission_term:
		base_filters.append(["admission_year", "=", admission_term])
		prev_filters.append(["admission_year", "=", admission_term])

	# -------------------------------------------------------------
	# 1. SECTION: OVERVIEW
	# -------------------------------------------------------------
	if section == "overview":
		total_new = frappe.db.count("CRM Contact", filters=base_filters)
		prev_new = frappe.db.count("CRM Contact", filters=prev_filters)
		delta_new = _get_delta(total_new, prev_new)

		active_filters = base_filters + [["enrollment_status", "not in", ["Đã nhập học", "Không quan tâm", "Sai số"]]]
		total_active = frappe.db.count("CRM Contact", filters=active_filters)
		prev_active = frappe.db.count("CRM Contact", filters=prev_filters + [["enrollment_status", "not in", ["Đã nhập học", "Không quan tâm", "Sai số"]]])
		delta_active = _get_delta(total_active, prev_active)

		enrolled_filters = base_filters + [["enrollment_status", "=", "Đã nhập học"]]
		total_enrolled = frappe.db.count("CRM Contact", filters=enrolled_filters)
		prev_enrolled = frappe.db.count("CRM Contact", filters=prev_filters + [["enrollment_status", "=", "Đã nhập học"]])
		delta_enrolled = _get_delta(total_enrolled, prev_enrolled)

		# SLA rate
		on_time_sla = frappe.db.count("CRM Contact", filters=base_filters + [["sla_status", "=", "Đúng SLA"]])
		sla_rate = round((on_time_sla / total_new * 100.0), 1) if total_new else 0.0

		# Overdue leads
		total_overdue = frappe.db.count("CRM Contact", filters=base_filters + [["next_follow_up", "<", now_datetime()]])
		prev_overdue = frappe.db.count("CRM Contact", filters=prev_filters + [["next_follow_up", "<", now_datetime()]])
		delta_overdue = _get_delta(total_overdue, prev_overdue)

		# Funnel breakdown
		stages = ["Lead mới", "Đã liên hệ", "Có triển vọng", "Đang tư vấn", "Đã nộp hồ sơ", "Đã nhập học"]
		funnel_data = [{"stage": s, "count": frappe.db.count("CRM Contact", filters=base_filters + [["enrollment_status", "=", s]])} for s in stages]

		# Weekly leads (last 12 weeks)
		weekly_data = []
		for i in range(12, 0, -1):
			w_start = str(add_days(to_date, -i * 7))
			w_end = str(add_days(to_date, -(i - 1) * 7))
			cnt = frappe.db.count("CRM Contact", filters=[["creation", ">=", w_start], ["creation", "<", w_end], ["is_test_record", "=", 0]])
			weekly_data.append({"week": f"T{13 - i}", "count": cnt})

		# Readiness distribution
		readiness_levels = [
			("Sẵn sàng cao", ["Level 3 - Có ý định nộp hồ sơ", "Level 4 - Sẵn sàng nhập học"]),
			("Đang cân nhắc", ["Level 2 - Đang so sánh"]),
			("Cần nuôi dưỡng", ["Level 1 - Đang tìm hiểu"]),
			("Chưa xác định", ["", "Level 0 - Chưa xác định", None]),
		]
		readiness_data = [
			{"readiness": label, "count": frappe.db.count("CRM Contact", filters=base_filters + [["readiness_level", "in", vals]])}
			for label, vals in readiness_levels
		]

		# Sales performance (top 5 staff by enrolled count)
		staff_list = frappe.db.get_all("CRM Staff", fields=["name", "full_name"], limit=10)
		sales_perf_data = []
		for st in staff_list:
			cnt = frappe.db.count("CRM Contact", filters=base_filters + [["assigned_to", "=", st.name], ["enrollment_status", "=", "Đã nhập học"]])
			sales_perf_data.append({"sales": st.full_name, "enrolled": cnt})
		sales_perf_data = sorted(sales_perf_data, key=lambda x: x["enrolled"], reverse=True)[:5]
		if not sales_perf_data:
			sales_perf_data = [{"sales": "Chưa có dữ liệu", "enrolled": 0}]

		return [
			{
				"name": "mock_new_leads",
				"type": "number_chart",
				"layout": {"x": 0, "y": 0, "w": 4, "h": 3, "i": "mock_new_leads"},
				"data": {"title": "Lead mới", "tooltip": "Lead tạo trong kỳ", "value": total_new, "delta": delta_new, "deltaSuffix": "%"},
			},
			{
				"name": "mock_active_leads",
				"type": "number_chart",
				"layout": {"x": 4, "y": 0, "w": 4, "h": 3, "i": "mock_active_leads"},
				"data": {"title": "Lead đang hoạt động", "tooltip": "Lead trong active pipeline", "value": total_active, "delta": delta_active, "deltaSuffix": "%"},
			},
			{
				"name": "mock_sla_rate",
				"type": "number_chart",
				"layout": {"x": 8, "y": 0, "w": 4, "h": 3, "i": "mock_sla_rate"},
				"data": {"title": "Đúng SLA liên hệ (%)", "tooltip": "Lead được liên hệ đúng SLA", "value": sla_rate, "delta": 0.0, "deltaSuffix": "%"},
			},
			{
				"name": "mock_overdue_leads",
				"type": "number_chart",
				"layout": {"x": 12, "y": 0, "w": 4, "h": 3, "i": "mock_overdue_leads"},
				"data": {"title": "Lead quá hạn", "tooltip": "Lead cần xử lý ngay", "value": total_overdue, "delta": delta_overdue, "deltaSuffix": "%"},
			},
			{
				"name": "mock_enrolled",
				"type": "number_chart",
				"layout": {"x": 16, "y": 0, "w": 4, "h": 3, "i": "mock_enrolled"},
				"data": {"title": "Đã nhập học", "tooltip": "Lead đã chuyển đổi trong kỳ", "value": total_enrolled, "delta": delta_enrolled, "deltaSuffix": "%"},
			},
			{
				"name": "mock_admission_funnel",
				"type": "axis_chart",
				"layout": {"x": 0, "y": 3, "w": 10, "h": 8, "i": "mock_admission_funnel"},
				"data": {
					"data": funnel_data,
					"title": "Funnel tuyển sinh",
					"subtitle": "Số Lead đã đi vào từng giai đoạn",
					"xAxis": {"title": "", "key": "stage", "type": "category"},
					"yAxis": {"title": "Số lượng"},
					"series": [{"name": "count", "type": "bar"}],
				},
			},
			{
				"name": "mock_weekly_leads",
				"type": "axis_chart",
				"layout": {"x": 10, "y": 3, "w": 10, "h": 8, "i": "mock_weekly_leads"},
				"data": {
					"data": weekly_data,
					"title": "Lead mới theo tuần",
					"subtitle": "Xu hướng 12 tuần gần nhất",
					"xAxis": {"title": "", "key": "week", "type": "category"},
					"yAxis": {"title": "Số lượng"},
					"series": [{"name": "count", "type": "line", "showDataPoints": True}],
				},
			},
			{
				"name": "mock_readiness",
				"type": "donut_chart",
				"layout": {"x": 0, "y": 11, "w": 8, "h": 8, "i": "mock_readiness"},
				"data": {
					"data": readiness_data,
					"title": "Mức sẵn sàng nhập học",
					"subtitle": "Phân bổ readiness hiện tại",
					"categoryColumn": "readiness",
					"valueColumn": "count",
				},
			},
			{
				"name": "mock_sales_performance",
				"type": "axis_chart",
				"layout": {"x": 8, "y": 11, "w": 12, "h": 8, "i": "mock_sales_performance"},
				"data": {
					"data": sales_perf_data,
					"title": "Hiệu suất tư vấn",
					"subtitle": "Enrollment theo nhân viên Sales",
					"xAxis": {"title": "", "key": "sales", "type": "category"},
					"yAxis": {"title": "Số lượng"},
					"series": [{"name": "enrolled", "type": "bar"}],
				},
			},
		]

	# -------------------------------------------------------------
	# 2. SECTION: INTERESTS
	# -------------------------------------------------------------
	if section == "interests":
		core_dimensions = [
			{"code": "COST", "title": "Chi phí", "theme": "orange", "color": "amber"},
			{"code": "PROGRAM_COMPETITOR", "title": "Ngành & trường khác", "theme": "red", "color": "violet"},
			{"code": "CAREER", "title": "Việc làm", "theme": "green", "color": "teal"},
			{"code": "STUDENT_LIFE", "title": "Hoạt động sinh viên", "theme": "blue", "color": "pink"},
			{"code": "ACCOMMODATION", "title": "Chỗ ở", "theme": "gray", "color": "cyan"},
			{"code": "ENROLLMENT_READINESS", "title": "Sẵn sàng nhập học", "theme": "green", "color": "blue"},
			{"code": "INTERESTED", "title": "Quan tâm", "theme": "yellow", "color": "yellow"},
			{"code": "OTHER", "title": "Khác", "theme": "gray", "color": "gray"},
		]

		total_contacts = frappe.db.count("CRM Contact", filters=base_filters) or 1
		interest_card_items = []
		funnel_rows = []
		insight_fields = {field.fieldname for field in frappe.get_meta("CRM AI Lead Insight").fields}
		ai_threshold = ai_staleness_threshold_seconds()
		if "ai_generated_at" not in insight_fields or ai_threshold is None:
			interest_freshness_sql = "AND 1 = 0"
			interest_freshness_params = ()
		else:
			interest_cutoff = (
				now_datetime() - timedelta(seconds=ai_threshold)
				if ai_threshold != float("inf")
				else None
			)
			interest_freshness_sql = "AND insight.ai_generated_at IS NOT NULL"
			interest_freshness_params = (interest_cutoff,) if interest_cutoff else ()
			if interest_cutoff:
				interest_freshness_sql += " AND insight.ai_generated_at >= %s"
		insight_scope_sql, insight_scope_params = _insight_scope_sql()

		for idx, dim in enumerate(core_dimensions):
			# Count distinct contacts with this interest
			cnt = frappe.db.sql(
				f"""
				SELECT COUNT(DISTINCT insight.contact)
				FROM `tabCRM AI Lead Insight Item` item
				JOIN `tabCRM AI Lead Insight` insight ON insight.name = item.parent
				WHERE item.parenttype = 'CRM AI Lead Insight'
				AND item.parentfield = 'items'
				AND item.dimension_code = %s
				AND item.item_kind = 'interest'
				{interest_freshness_sql}
				{insight_scope_sql}
				""",
				(dim["code"], *interest_freshness_params, *insight_scope_params),
			)[0][0] or 0

			ratio_pct = round((cnt / total_contacts * 100.0), 1)
			enrolled_with_dim = frappe.db.sql(
				f"""
				SELECT COUNT(DISTINCT c.name)
				FROM `tabCRM Contact` c
				JOIN `tabCRM AI Lead Insight` insight ON insight.contact = c.name
				JOIN `tabCRM AI Lead Insight Item` i ON i.parent = insight.name
				WHERE i.parenttype = 'CRM AI Lead Insight'
				AND i.parentfield = 'items'
				AND i.dimension_code = %s
				AND i.item_kind = 'interest'
				{interest_freshness_sql}
				{insight_scope_sql}
				AND c.enrollment_status = 'Đã nhập học'
				""",
				(dim["code"], *interest_freshness_params, *insight_scope_params),
			)[0][0] or 0
			conv_rate = f"{round((enrolled_with_dim / cnt * 100.0), 1)}%" if cnt else "0.0%"

			card_data = {
				"code": dim["code"],
				"title": dim["title"],
				"value": cnt,
				"ratio": f"{ratio_pct}% active",
				"progress": min(100, int((cnt / total_contacts) * 100)),
				"sparkline": [cnt, cnt, cnt, cnt, cnt, cnt, cnt] if cnt else [0, 0, 0, 0, 0, 0, 0],
				"metrics": [
					{"label": "15 phút", "value": "+0"},
					{"label": "So với hôm qua", "value": "+0.0%"},
					{"label": "Đang tăng", "value": cnt},
					{"label": "Confidence thấp", "value": 0},
				],
				"conversion": conv_rate,
				"trend": "Ổn định",
				"theme": dim["theme"],
				"color": dim["color"],
			}

			if dim["code"] == "ENROLLMENT_READINESS":
				l0 = frappe.db.count("CRM Contact", filters=base_filters + [["readiness_level", "in", ["", "Level 0 - Chưa xác định", None]]])
				l1 = frappe.db.count("CRM Contact", filters=base_filters + [["readiness_level", "=", "Level 1 - Đang tìm hiểu"]])
				l2 = frappe.db.count("CRM Contact", filters=base_filters + [["readiness_level", "=", "Level 2 - Đang so sánh"]])
				l3 = frappe.db.count("CRM Contact", filters=base_filters + [["readiness_level", "=", "Level 3 - Có ý định nộp hồ sơ"]])
				l4 = frappe.db.count("CRM Contact", filters=base_filters + [["readiness_level", "=", "Level 4 - Sẵn sàng nhập học"]])
				card_data["readinessTotal"] = total_contacts
				card_data["readinessLevels"] = [
					{"level": 0, "count": l0, "share": round(l0 / total_contacts * 100, 1)},
					{"level": 1, "count": l1, "share": round(l1 / total_contacts * 100, 1)},
					{"level": 2, "count": l2, "share": round(l2 / total_contacts * 100, 1)},
					{"level": 3, "count": l3, "share": round(l3 / total_contacts * 100, 1)},
					{"level": 4, "count": l4, "share": round(l4 / total_contacts * 100, 1)},
				]
				card_data["operationalMetrics"] = [
					{"label": "Đã có hồ sơ", "value": frappe.db.count("CRM Contact", filters=base_filters + [["enrollment_status", "=", "Đã nộp hồ sơ"]])},
					{"label": "Chưa follow-up", "value": frappe.db.count("CRM Contact", filters=base_filters + [["next_follow_up", "is", "not set"]])},
					{"label": "Quá SLA", "value": frappe.db.count("CRM Contact", filters=base_filters + [["sla_status", "=", "Quá SLA"]])},
				]

			item_name = f"mock_interest_{dim['code'].lower()}"
			interest_card_items.append({
				"name": item_name,
				"type": "interest_card",
				"layout": {"x": (idx % 4) * 5, "y": 0 if idx < 4 else 7, "w": 5, "h": 7, "i": item_name},
				"data": card_data,
			})

			# Build funnel row
			if idx < 5:
				funnel_rows.append({
					"label": dim["title"],
					"total": cnt,
					"enrolled": enrolled_with_dim,
					"ariaLabel": f"{dim['title']}: {cnt} Lead, {enrolled_with_dim} Đã nhập học",
					"segments": [
						{"label": "Không chuyển đổi", "value": max(0, cnt - enrolled_with_dim), "share": round(max(0, cnt - enrolled_with_dim) / (cnt or 1) * 100, 1), "class": "bg-gray-300"},
						{"label": "Đã nhập học", "value": enrolled_with_dim, "share": round(enrolled_with_dim / (cnt or 1) * 100, 1), "class": "bg-green-600"},
					],
				})

		funnel_item = {
			"name": "mock_interest_funnel",
			"type": "conversion_funnel",
			"layout": {"x": 0, "y": 14, "w": 10, "h": 9, "i": "mock_interest_funnel"},
			"data": {
				"title": "Interest × Funnel",
				"subtitle": "Tỷ trọng chuyển đổi và điểm rơi theo từng mối quan tâm",
				"legend": [
					{"label": "Không chuyển đổi", "class": "bg-gray-300"},
					{"label": "Mới", "class": "bg-red-600"},
					{"label": "Có triển vọng", "class": "bg-red-400"},
					{"label": "Đã xác nhận", "class": "bg-orange-500"},
					{"label": "Đã nhập học", "class": "bg-green-600"},
				],
				"rows": funnel_rows,
			},
		}

		labels_5 = ["Chi phí", "Ngành/trường", "Việc làm", "Hoạt động", "Chỗ ở"]
		overlap_item = {
			"name": "mock_interest_overlap",
			"type": "overlap_heatmap",
			"layout": {"x": 10, "y": 14, "w": 10, "h": 9, "i": "mock_interest_overlap"},
			"data": {
				"title": "Interest Overlap Matrix",
				"subtitle": "Số Lead đồng thời thuộc cả hai mối quan tâm · đường chéo là tổng Lead",
				"symmetric": True,
				"max": max(1, total_contacts),
				"labels": labels_5,
				"rows": [
					{"label": lbl, "values": [0 for _ in labels_5]}
					for lbl in labels_5
				],
			},
		}

		return interest_card_items + [funnel_item, overlap_item]

	# -------------------------------------------------------------
	# 3. SECTION: ACTIONS
	# -------------------------------------------------------------
	if section == "actions":
		# Signal feed: get latest insights from CRM AI Lead Insight
		insight_fields = {field.fieldname for field in frappe.get_meta("CRM AI Lead Insight").fields}
		fields = ["name", "contact", "summary", "generated_at"]
		if "ai_summary" in insight_fields:
			fields.append("ai_summary")
		if "ai_generated_at" in insight_fields:
			fields.append("ai_generated_at")
		# `get_list` is intentional here: it applies the Student-linked row-scope
		# hook for CRM AI Lead Insight. `db.get_all` would bypass that boundary.
		insights = frappe.get_list(
			"CRM AI Lead Insight",
			fields=fields,
			order_by=("ai_generated_at desc, generated_at desc" if "ai_generated_at" in insight_fields else "generated_at desc"),
			limit=10,
		)
		signals = []
		for ins in insights:
			c_name = frappe.db.get_value("CRM Contact", ins["contact"], "full_name") or ins["contact"]
			if "ai_generated_at" not in insight_fields:
				# Pre-migration schema: preserve the legacy signal feed exactly.
				generated_at = ins.get("generated_at")
				message = ins.get("summary") or "Có tương tác mới được AI phân tích."
				ai_available = None
				reason = None
			elif "ai_summary" not in insight_fields:
				# A partial migration must not expose the legacy value as current AI
				# analysis merely because the timestamp column arrived first.
				generated_at = ins.get("generated_at")
				message = "Phân tích AI tạm không khả dụng."
				ai_available = False
				reason = "schema_incomplete"
			else:
				ai_summary = ai_field_or_unavailable(ins, "ai_summary")
				generated_at = ai_summary.get("generated_at")
				message = ai_summary.get("value") if ai_summary["ai_available"] else "Phân tích AI tạm không khả dụng."
				ai_available = ai_summary["ai_available"]
				reason = ai_summary.get("reason")
			time_str = frappe.utils.format_time(generated_at, "HH:mm") if generated_at else "Vừa xong"
			signal = {
				"time": time_str,
				"lead": c_name,
				"message": message,
			}
			if ai_available is not None:
				signal.update({"ai_available": ai_available, "reason": reason})
			signals.append(signal)

		if not signals:
			signals = [{"time": "--:--", "lead": "Hệ thống", "message": "Chưa có tín hiệu tương tác mới nào."}]

		signal_item = {
			"name": "mock_signal_feed",
			"type": "signal_feed",
			"layout": {"x": 0, "y": 0, "w": 7, "h": 10, "i": "mock_signal_feed"},
			"data": {
				"title": "Tín hiệu AI mới nhất",
				"subtitle": "Cập nhật theo tương tác học sinh",
				"signals": signals,
			},
		}

		# Actionable leads: Contacts with high readiness or overdue follow up
		action_contacts = frappe.db.get_all(
			"CRM Contact",
			filters=base_filters,
			fields=["name", "full_name", "assigned_to", "enrollment_status", "readiness_level", "next_follow_up"],
			order_by="modified desc",
			limit=10,
		)
		action_rows = []
		for ac in action_contacts:
			owner_name = frappe.db.get_value("CRM Staff", ac["assigned_to"], "full_name") or "Chưa phân công"
			action_rows.append({
				"lead": ac["full_name"] or ac["name"],
				"owner": owner_name,
				"stage": ac["enrollment_status"] or "Mới",
				"interest": "Tư vấn tuyển sinh",
				"readiness": 3 if "Level 3" in (ac["readiness_level"] or "") else 2,
				"followUp": str(ac["next_follow_up"]) if ac["next_follow_up"] else "Chưa có",
				"action": "Liên hệ tư vấn chính sách",
			})

		actionable_item = {
			"name": "mock_actionable_leads",
			"type": "data_table",
			"layout": {"x": 7, "y": 0, "w": 13, "h": 10, "i": "mock_actionable_leads"},
			"data": {
				"title": "Lead cần hành động",
				"subtitle": "Danh sách Lead ưu tiên follow-up trong ngày",
				"badge": f"{len(action_rows)} Lead cần xử lý",
				"drilldown": True,
				"columns": [
					{"key": "lead", "label": "Lead", "primary": True},
					{"key": "owner", "label": "Sales Owner"},
					{"key": "stage", "label": "Giai đoạn"},
					{"key": "followUp", "label": "Next Follow-up"},
					{"key": "action", "label": "Recommended Action"},
				],
				"rows": action_rows,
			},
		}

		# Staff breakdown
		staff_rows = frappe.db.get_all("CRM Staff", fields=["name", "full_name"], limit=5)
		owner_rows = []
		for st in staff_rows:
			tot = frappe.db.count("CRM Contact", filters=base_filters + [["assigned_to", "=", st.name]])
			no_follow = frappe.db.count("CRM Contact", filters=base_filters + [["assigned_to", "=", st.name], ["next_follow_up", "is", "not set"]])
			owner_rows.append({
				"sales": st.full_name,
				"cost": int(tot * 0.3),
				"program": int(tot * 0.2),
				"career": int(tot * 0.4),
				"ready": frappe.db.count("CRM Contact", filters=base_filters + [["assigned_to", "=", st.name], ["readiness_level", "like", "%Level 3%"]]),
				"noFollowUp": no_follow,
				"lowConfidence": 0,
			})

		owner_item = {
			"name": "mock_interest_owner",
			"type": "data_table",
			"layout": {"x": 0, "y": 10, "w": 20, "h": 9, "i": "mock_interest_owner"},
			"data": {
				"title": "Interest × Sales Owner",
				"subtitle": "Khối lượng Lead và follow-up theo nhân viên Sales",
				"badge": f"{len(staff_rows)} nhân viên",
				"columns": [
					{"key": "sales", "label": "Sales", "primary": True},
					{"key": "cost", "label": "Chi phí"},
					{"key": "program", "label": "Ngành/trường"},
					{"key": "career", "label": "Việc làm"},
					{"key": "ready", "label": "Ready"},
					{"key": "noFollowUp", "label": "Chưa follow-up"},
				],
				"rows": owner_rows,
			},
		}

		return [signal_item, actionable_item, owner_item]

	return []


def _campaign_spend_total(campaign, from_date, to_date):
	"""Read spend from the canonical performance fact, with legacy read fallback."""
	if frappe.db.table_exists("CRM Campaign Performance Fact"):
		filters = [["period_start", "<=", to_date], ["period_end", ">=", from_date]]
		if campaign:
			filters.append(["campaign", "=", campaign])
		return sum(row.spend or 0.0 for row in frappe.db.get_all("CRM Campaign Performance Fact", filters=filters, fields=["spend"]))
	if not frappe.db.table_exists("CRM Campaign Spend"):
		return 0.0
	filters = [["spend_date", "between", [from_date, to_date]]]
	if campaign:
		filters.append(["crm_campaign", "=", campaign])
	return sum(row.amount or 0.0 for row in frappe.db.get_all("CRM Campaign Spend", filters=filters, fields=["amount"]))


def _contact_names_touched_by_campaign(campaign):
	"""Contacts with campaign attribution, read from the canonical
	CRM Marketing Engagement table (CRM Contact.crm_campaign was migrated into
	it and retired)."""
	return set(frappe.db.get_all("CRM Marketing Engagement", filters={"engagement_kind": "campaign_touch", "crm_campaign": campaign}, pluck="crm_contact"))


def _contact_names_with_event_participation():
	"""Contacts with event participation, read from the canonical
	CRM Marketing Engagement table (CRM Contact.crm_event was migrated into
	it and retired)."""
	return set(frappe.db.get_all("CRM Marketing Engagement", filters={"engagement_kind": "event_participation"}, pluck="crm_contact"))


def _campaign_cost_data(campaign_list, from_date, to_date, base_filters):
	"""Per-campaign spend / last-touch-attributed conversions / cost-per-
	conversion, shared by get_digital_marketing_dashboard and
	get_admissions_director_dashboard so the two views can't silently diverge
	(condition #6). Computes the site-wide last-touch-by-contact map ONCE
	(not once per campaign -- get_campaign_names_by_last_touch would re-scan
	both junction tables on every loop iteration) and buckets it in memory."""
	# Existing dashboard filters are Contact-scoped. Resolve the bounded Student
	# cohort once, then run the canonical Student-first attribution projection
	# against that cohort so campus/date/source filters are not dropped.
	scoped_contacts = set(frappe.get_list("CRM Contact", filters=base_filters, pluck="name", limit_page_length=0))
	scoped_students = {
		student
		for contact in scoped_contacts
		for student in students_for_contact(contact)
	}
	last_touch_by_student = get_last_touch_campaign_by_student(scoped_students)
	students_by_campaign = {}
	for student, campaign in last_touch_by_student.items():
		students_by_campaign.setdefault(campaign, set()).add(student)
	cost_data = []
	for camp in campaign_list:
		c_name = camp.title or camp.name
		camp_spend = _campaign_spend_total(camp.name, from_date, to_date)
		attributed_students = students_by_campaign.get(camp.name) or set()
		# Attribution is Student-first. Contact-only filters are intentionally
		# not applied to this canonical projection.
		count_rows = frappe.get_list(
			"CRM Student",
			filters=[["name", "in", list(attributed_students) or ["__none__"]], ["enrollment_status", "=", "Đã nhập học"]],
			fields=["count(name) as count"],
			limit_page_length=1,
		)
		attributed_conversions = int(count_rows[0].get("count") or 0) if count_rows else 0
		cost_data.append({
			"campaign": c_name,
			"spend": camp_spend,
			"attributedConversions": attributed_conversions,
			"costPerConversion": round(camp_spend / attributed_conversions, 0) if attributed_conversions and camp_spend else 0.0,
		})
	return cost_data


@frappe.whitelist()
def get_digital_marketing_dashboard(
	from_date=None,
	to_date=None,
	source=None,
	platform=None,
	campaign=None,
	campus=None,
):
	check_dashboard_access("digital_marketing")
	from_date, to_date = _normalize_date_range(from_date, to_date)
	to_date_plus_1 = str(add_days(to_date, 1))

	base_filters = [
		["creation", ">=", from_date],
		["creation", "<", to_date_plus_1],
		["is_test_record", "=", 0],
	]

	# Filter digital sources
	digital_sources = frappe.db.get_all("CRM Lead Source", filters={"is_digital": 1}, pluck="name") or ["Facebook", "Google", "Zalo", "TikTok", "Website"]
	base_filters.append(["source", "in", digital_sources])

	if source:
		base_filters.append(["source", "=", source])
	if platform:
		base_filters.append(["platform", "=", platform])
	if campaign:
		base_filters.append(["name", "in", list(_contact_names_touched_by_campaign(campaign))])
	if campus:
		base_filters.append(["branch", "=", campus])

	total_digital_leads = frappe.db.count("CRM Contact", filters=base_filters)
	valid_leads = frappe.db.count("CRM Contact", filters=base_filters + [["phone", "is", "set"]])
	valid_rate = round((valid_leads / total_digital_leads * 100.0), 1) if total_digital_leads else 0.0

	qualified_leads = frappe.db.count("CRM Contact", filters=base_filters + [["enrollment_status", "in", ["Có triển vọng", "Đang tư vấn", "Đã nộp hồ sơ", "Đã nhập học"]]])
	qualified_rate = round((qualified_leads / total_digital_leads * 100.0), 1) if total_digital_leads else 0.0

	# Spend from CRM Campaign Spend -- scoped to the selected campaign when one
	# is filtered, so CPL/cost-per-enrollment reflect that campaign's own spend
	# instead of the site-wide total (previously a flat total regardless of
	# the `campaign` filter, which misrepresented per-campaign cost).
	total_spend = _campaign_spend_total(campaign, from_date, to_date)

	cpl = round(total_spend / total_digital_leads / 1000, 1) if total_digital_leads and total_spend else 0.0
	enrolled_leads = frappe.db.count("CRM Contact", filters=base_filters + [["enrollment_status", "=", "Đã nhập học"]])
	cost_enrollment = round(total_spend / enrolled_leads / 1000000, 1) if enrolled_leads and total_spend else 0.0

	# Platform Breakdown
	sources_list = ["Facebook", "Google", "Zalo", "Website", "TikTok", "Referral"]
	leads_by_platform = []
	for s in sources_list:
		c = frappe.db.count("CRM Contact", filters=[["creation", ">=", from_date], ["creation", "<", to_date_plus_1], ["source", "=", s], ["is_test_record", "=", 0]])
		leads_by_platform.append({"platform": s, "count": c})

	# Form vs Landing Page Split
	fb_form = frappe.db.count("CRM Contact", filters=[["creation", ">=", from_date], ["creation", "<", to_date_plus_1], ["source", "=", "Facebook"], ["platform", "like", "%Form%"]])
	fb_landing = frappe.db.count("CRM Contact", filters=[["creation", ">=", from_date], ["creation", "<", to_date_plus_1], ["source", "=", "Facebook"], ["platform", "like", "%Landing%"]])
	gg_form = frappe.db.count("CRM Contact", filters=[["creation", ">=", from_date], ["creation", "<", to_date_plus_1], ["source", "=", "Google"], ["platform", "like", "%Form%"]])
	gg_landing = frappe.db.count("CRM Contact", filters=[["creation", ">=", from_date], ["creation", "<", to_date_plus_1], ["source", "=", "Google"], ["platform", "like", "%Landing%"]])

	form_landing_split = [
		{"platform": "Facebook", "Form": fb_form, "Landing Page": fb_landing},
		{"platform": "Google", "Form": gg_form, "Landing Page": gg_landing},
	]

	# Source Platform Matrix
	matrix_rows = [
		{"label": "Facebook", "values": [fb_form, fb_landing, None]},
		{"label": "Google", "values": [gg_form, gg_landing, None]},
		{"label": "Zalo", "values": [None, None, frappe.db.count("CRM Contact", filters=base_filters + [["source", "=", "Zalo"]])]},
		{"label": "TikTok", "values": [None, None, frappe.db.count("CRM Contact", filters=base_filters + [["source", "=", "TikTok"]])]},
		{"label": "Referral", "values": [None, None, frappe.db.count("CRM Contact", filters=[["creation", ">=", from_date], ["creation", "<", to_date_plus_1], ["source", "=", "Referral"]])]},
		{"label": "Website", "values": [None, None, frappe.db.count("CRM Contact", filters=base_filters + [["source", "=", "Website"]])]},
	]

	# Source Quality
	source_quality = []
	for s in sources_list:
		q = frappe.db.count("CRM Contact", filters=[["creation", ">=", from_date], ["creation", "<", to_date_plus_1], ["source", "=", s], ["enrollment_status", "in", ["Có triển vọng", "Đang tư vấn", "Đã nộp hồ sơ", "Đã nhập học"]]])
		source_quality.append({"source": s, "qualified": q})

	# Campaign Contact: Query active CRM Campaigns
	campaign_list = frappe.db.get_all("CRM Campaign", fields=["name", "title"], limit=5)
	campaign_data = []
	for camp in campaign_list:
		c_name = camp.title or camp.name
		c_filters = base_filters + [["name", "in", list(_contact_names_touched_by_campaign(camp.name))]]
		campaign_data.append({
			"campaign": c_name,
			"Đã chuyển đổi": frappe.db.count("CRM Contact", filters=c_filters + [["enrollment_status", "=", "Đã nhập học"]]),
			"Có triển vọng": frappe.db.count("CRM Contact", filters=c_filters + [["enrollment_status", "=", "Có triển vọng"]]),
			"Sai số": frappe.db.count("CRM Contact", filters=c_filters + [["quality_bucket", "=", "Sai số"]]),
			"Sai đối tượng": frappe.db.count("CRM Contact", filters=c_filters + [["quality_bucket", "=", "Không quan tâm"]]),
			"Không liên lạc được": frappe.db.count("CRM Contact", filters=c_filters + [["quality_bucket", "=", "Không liên lạc được"]]),
		})

	# Cost-per-outcome: spend per campaign vs. its LAST-TOUCH-attributed
	# conversions (Phase 6), not just "ever touched" conversions -- a lead
	# touched early by this campaign but converted via a later campaign's
	# touch shouldn't count as this campaign's conversion.
	campaign_cost_data = _campaign_cost_data(campaign_list, from_date, to_date, base_filters)

	if not campaign_data:
		campaign_data = [{"campaign": "Chưa có chiến dịch", "Đã chuyển đổi": 0, "Có triển vọng": 0, "Sai số": 0, "Sai đối tượng": 0, "Không liên lạc được": 0}]

	# Primary Interest
	primary_interests = [
		{"interest": "Cơ hội nghề nghiệp", "count": frappe.db.count("CRM Contact", filters=base_filters + [["notes", "like", "%nghề nghiệp%"]])},
		{"interest": "Học phí & học bổng", "count": frappe.db.count("CRM Contact", filters=base_filters + [["notes", "like", "%học phí%"]])},
		{"interest": "Chương trình đào tạo", "count": frappe.db.count("CRM Contact", filters=base_filters + [["major", "is", "set"]])},
		{"interest": "Môi trường quốc tế", "count": frappe.db.count("CRM Contact", filters=base_filters + [["notes", "like", "%quốc tế%"]])},
	]

	items = [
		{"name": "mock_marketing_leads", "type": "number_chart", "layout": {"x": 0, "y": 0, "w": 4, "h": 3, "i": "mock_marketing_leads"}, "data": {"title": "Digital Marketing", "tooltip": "Lead đến từ các nguồn Digital", "value": total_digital_leads, "delta": 0.0, "deltaSuffix": "%"}},
		{"name": "mock_valid_rate", "type": "number_chart", "layout": {"x": 4, "y": 0, "w": 4, "h": 3, "i": "mock_valid_rate"}, "data": {"title": "Valid Lead Rate (%)", "tooltip": "Tỷ lệ Lead hợp lệ", "value": valid_rate, "delta": 0.0, "deltaSuffix": "%"}},
		{"name": "mock_qualified_rate", "type": "number_chart", "layout": {"x": 8, "y": 0, "w": 4, "h": 3, "i": "mock_qualified_rate"}, "data": {"title": "Qualified Rate (%)", "tooltip": "Tỷ lệ Lead đủ điều kiện", "value": qualified_rate, "delta": 0.0, "deltaSuffix": "%"}},
		{"name": "mock_cpl", "type": "number_chart", "layout": {"x": 12, "y": 0, "w": 4, "h": 3, "i": "mock_cpl"}, "data": {"title": "CPL (nghìn đồng)", "tooltip": "Chi phí trung bình trên mỗi Lead", "value": cpl, "delta": 0.0, "deltaSuffix": "%"}},
		{"name": "mock_cost_enrollment", "type": "number_chart", "layout": {"x": 16, "y": 0, "w": 4, "h": 3, "i": "mock_cost_enrollment"}, "data": {"title": "Chi phí / Enrollment (triệu)", "tooltip": "Chi phí trung bình trên mỗi enrollment", "value": cost_enrollment, "delta": 0.0, "deltaSuffix": "%"}},
		{"name": "mock_leads_by_platform", "type": "donut_chart", "layout": {"x": 0, "y": 3, "w": 10, "h": 8, "i": "mock_leads_by_platform"}, "data": {"data": leads_by_platform, "title": "Lead theo Platform", "subtitle": "Phân bổ Lead theo nhóm nguồn (Lead Source)", "categoryColumn": "platform", "valueColumn": "count"}},
		{
			"name": "mock_form_landing_split",
			"type": "axis_chart",
			"layout": {"x": 10, "y": 3, "w": 10, "h": 8, "i": "mock_form_landing_split"},
			"data": {
				"data": form_landing_split,
				"title": "Chi tiết Form vs Landing Page",
				"subtitle": "Facebook & Google là 2 nguồn có tách sub-channel",
				"xAxis": {"title": "", "key": "platform", "type": "category"},
				"yAxis": {"title": "Số lượng"},
				"series": [{"name": "Form", "type": "bar"}, {"name": "Landing Page", "type": "bar"}],
			},
		},
		{
			"name": "mock_source_platform_matrix",
			"type": "overlap_heatmap",
			"layout": {"x": 0, "y": 11, "w": 10, "h": 9, "i": "mock_source_platform_matrix"},
			"data": {
				"title": "Ma trận Nguồn × Platform",
				"subtitle": "Số Lead theo từng Lead Source và sub-channel (Platform) tương ứng",
				"max": max(1, total_digital_leads),
				"labels": ["Form", "Landing Page", "Trực tiếp"],
				"rows": matrix_rows,
			},
		},
		{
			"name": "mock_source_quality",
			"type": "axis_chart",
			"layout": {"x": 10, "y": 11, "w": 10, "h": 9, "i": "mock_source_quality"},
			"data": {
				"data": source_quality,
				"title": "Qualified Lead theo nguồn",
				"subtitle": "Chất lượng Lead theo Lead Source",
				"xAxis": {"title": "", "key": "source", "type": "category"},
				"yAxis": {"title": "Số lượng"},
				"series": [{"name": "qualified", "type": "bar"}],
			},
		},
		{
			"name": "mock_campaign_contact",
			"type": "axis_chart",
			"layout": {"x": 0, "y": 20, "w": 12, "h": 8, "i": "mock_campaign_contact"},
			"data": {
				"data": campaign_data,
				"title": "Contact theo chiến dịch",
				"subtitle": "Phân bổ Contact theo trạng thái Lead cho từng chiến dịch",
				"xAxis": {"title": "", "key": "campaign", "type": "category"},
				"yAxis": {"title": "Số lượng"},
				"series": [
					{"name": "Đã chuyển đổi", "type": "bar"},
					{"name": "Có triển vọng", "type": "bar"},
					{"name": "Sai số", "type": "bar"},
					{"name": "Sai đối tượng", "type": "bar"},
					{"name": "Không liên lạc được", "type": "bar"},
				],
			},
		},
		{
			"name": "mock_primary_interest",
			"type": "donut_chart",
			"layout": {"x": 12, "y": 20, "w": 8, "h": 8, "i": "mock_primary_interest"},
			"data": {
				"data": primary_interests,
				"title": "Mối quan tâm nổi bật",
				"subtitle": "Tổng hợp từ Lead Interest Event",
				"categoryColumn": "interest",
				"valueColumn": "count",
			},
		},
		{
			"name": "mock_campaign_cost",
			"type": "axis_chart",
			"layout": {"x": 0, "y": 28, "w": 12, "h": 8, "i": "mock_campaign_cost"},
			"data": {
				"data": campaign_cost_data,
				"title": "Chi phí / Chuyển đổi theo chiến dịch",
				"subtitle": "Chi phí thực tế so với số chuyển đổi được attribute (last-touch) cho từng chiến dịch",
				"xAxis": {"title": "", "key": "campaign", "type": "category"},
				"yAxis": {"title": "Giá trị"},
				"series": [
					{"name": "spend", "type": "bar"},
					{"name": "attributedConversions", "type": "bar"},
					{"name": "costPerConversion", "type": "bar"},
				],
			},
		},
	]

	return items


@frappe.whitelist()
def get_offline_marketing_dashboard(team="all", from_date=None, to_date=None, campus=None):
	check_dashboard_access("offline_marketing")
	from_date, to_date = _normalize_date_range(from_date, to_date)
	to_date_plus_1 = str(add_days(to_date, 1))
	is_filtered = team != "all"

	base_filters = [
		["creation", ">=", from_date],
		["creation", "<", to_date_plus_1],
		["is_test_record", "=", 0],
	]
	if campus:
		base_filters.append(["branch", "=", campus])

	# Filter by staff sales_team if team is selected
	if is_filtered:
		staff_in_team = _staff_names_in_sales_team(team)
		base_filters.append(["assigned_to", "in", staff_in_team])

	# Region counts (Bắc, Trung, Nam)
	event_participant_names = list(_contact_names_with_event_participation())
	regions = ["Miền Bắc", "Miền Trung", "Miền Nam"]
	region_data = []
	for r in (regions if not is_filtered else [("Miền Bắc" if team == "Team North" else "Miền Trung" if team == "Team Central" else "Miền Nam")]):
		provinces_in_reg = frappe.db.get_all("CRM Province", filters={"region": r}, pluck="name")
		region_filters = base_filters + [["province", "in", provinces_in_reg]]
		if event_participant_names:
			on_c = frappe.db.count("CRM Contact", filters=region_filters + [["name", "in", event_participant_names]])
			off_c = frappe.db.count("CRM Contact", filters=region_filters + [["name", "not in", event_participant_names]])
		else:
			on_c = 0
			off_c = frappe.db.count("CRM Contact", filters=region_filters)
		region_data.append({"region": r, "On-campus": on_c, "Off-campus": off_c})

	# Interest data
	interests = [
		"Học phí & học bổng",
		"Ngành đào tạo",
		"Cơ hội việc làm",
		"Môi trường sinh viên",
		"Khác",
	]
	interest_data = [
		{"interest": it, "count": frappe.db.count("CRM Contact", filters=base_filters + [["notes", "like", f"%{it[:6]}%"]])}
		for it in interests
	]

	# Lead quality chart (6 categories)
	quality_buckets = ["Hot", "Warm", "Cool", "Sai số", "Không liên lạc được", "Không quan tâm"]
	quality_data = [
		{"category": q, "count": frappe.db.count("CRM Contact", filters=base_filters + [["quality_bucket", "=", q]])}
		for q in quality_buckets
	]

	# Verified Lead by Province
	# Canonical province former-name children.
	mappings = [
		{"old_province": row.former_name, "new_province": row.parent}
		for row in frappe.db.get_all("CRM Province Former Name", fields=["former_name", "parent"], filters={"parentfield": "previous_names"})
	]
	province_rows = []
	if mappings:
		province_groups = {}
		for m in mappings:
			v_count = frappe.db.count("CRM Contact", filters=base_filters + [["province", "=", m["old_province"]], ["is_verified_lead", "=", 1]])
			if is_filtered:
				province_rows.append({"province": m["old_province"], "verified": v_count})
			else:
				group = province_groups.setdefault(
					m["new_province"],
					{"province": m["new_province"], "province_detail": [], "verified": 0},
				)
				group["province_detail"].append(m["old_province"])
				group["verified"] += v_count
		if not is_filtered:
			province_rows = [
				{
					"province": group["province"],
					"province_detail": ", ".join(group["province_detail"]),
					"verified": group["verified"],
				}
				for group in province_groups.values()
			]
	else:
		# Fallback to CRM Province
		top_provinces = frappe.db.get_all("CRM Province", fields=["name"], limit=6)
		for p in top_provinces:
			v_count = frappe.db.count("CRM Contact", filters=base_filters + [["province", "=", p.name], ["is_verified_lead", "=", 1]])
			province_rows.append({"province": p.name, "verified": v_count})

	event_chart = {
		"name": "mock_offline_region",
		"type": "axis_chart",
		"layout": {"x": 0, "y": 0, "w": 10, "h": 8, "i": "mock_offline_region"},
		"data": {
			"data": region_data,
			"title": "Lead theo Khu vực & Hình thức sự kiện",
			"subtitle": f"Team đang chọn: {team}" if is_filtered else "Tổng quan tất cả team · On-campus vs Off-campus",
			"xAxis": {"title": "", "key": "region", "type": "category"},
			"yAxis": {"title": "Số lượng"},
			"series": [{"name": "On-campus", "type": "bar"}, {"name": "Off-campus", "type": "bar"}],
		},
	}

	interest_chart = {
		"name": "mock_offline_interest",
		"type": "donut_chart",
		"layout": {"x": 10, "y": 0, "w": 10, "h": 8, "i": "mock_offline_interest"},
		"data": {
			"data": interest_data,
			"title": "Mối quan tâm từ sự kiện",
			"subtitle": f"Team đang chọn: {team}" if is_filtered else "Tổng quan tất cả team",
			"categoryColumn": "interest",
			"valueColumn": "count",
		},
	}

	lead_quality_chart = {
		"name": "mock_offline_lead_quality",
		"type": "axis_chart",
		"layout": {"x": 0, "y": 8, "w": 10, "h": 8, "i": "mock_offline_lead_quality"},
		"data": {
			"data": quality_data,
			"title": "Lead thu được theo phân loại",
			"subtitle": "Toàn bộ Lead thu được từ sự kiện On-campus & Off-campus",
			"xAxis": {"title": "", "key": "category", "type": "category"},
			"yAxis": {"title": "Số lượng"},
			"series": [{"name": "count", "type": "bar"}],
			"echartOptions": {
				"xAxis": {
					"axisLabel": {
						"interval": 0,
						"fontSize": 11,
					},
				},
			},
		},
	}

	province_chart = {
		"name": "mock_offline_province",
		"type": "axis_chart",
		"layout": {"x": 10, "y": 8, "w": 10, "h": 8, "i": "mock_offline_province"},
		"data": {
			"data": province_rows,
			"title": "Verified Lead theo địa bàn",
			"subtitle": f"Team đang chọn: {team} · chỉ hiện tỉnh cũ"
			if is_filtered
			else "Tỉnh mới · gộp từ nhiều tỉnh cũ",
			"xAxis": {"title": "", "key": "province", "type": "category", "wrapLabels": True},
			"yAxis": {"title": "Verified Lead"},
			"series": [{"name": "verified", "type": "bar"}],
			"echartOptions": {
				"xAxis": {
					"axisLabel": {
						"interval": 0,
						"rotate": 0,
						"fontSize": 11,
					},
				},
			},
		},
	}

	return [event_chart, interest_chart, lead_quality_chart, province_chart]


@frappe.whitelist()
def get_admissions_director_dashboard(from_date=None, to_date=None, campus=None):
	"""Cross-functional summary for Admissions Director/Operations: the same
	underlying funnel, spend, and attribution data as the Sales/Digital/Offline
	dashboards, reconciled into one view instead of three separately-scoped
	ones (Phase 6 reconciliation requirement)."""
	check_dashboard_access("admissions_director")
	from_date, to_date = _normalize_date_range(from_date, to_date)
	to_date_plus_1 = str(add_days(to_date, 1))

	base_filters = [
		["creation", ">=", from_date],
		["creation", "<", to_date_plus_1],
		["is_test_record", "=", 0],
	]
	if campus:
		base_filters.append(["branch", "=", campus])

	total_leads = frappe.db.count("CRM Contact", filters=base_filters)
	qualified_leads = frappe.db.count(
		"CRM Contact",
		filters=base_filters + [["enrollment_status", "in", ["Có triển vọng", "Đang tư vấn", "Đã nộp hồ sơ", "Đã nhập học"]]],
	)
	enrolled_leads = frappe.db.count("CRM Contact", filters=base_filters + [["enrollment_status", "=", "Đã nhập học"]])
	qualified_rate = round((qualified_leads / total_leads * 100.0), 1) if total_leads else 0.0
	conversion_rate = round((enrolled_leads / total_leads * 100.0), 1) if total_leads else 0.0

	total_spend = _campaign_spend_total(None, from_date, to_date)
	cost_per_enrollment = round(total_spend / enrolled_leads / 1000000, 1) if enrolled_leads and total_spend else 0.0

	# Per-campaign last-touch spend/conversion reconciliation -- same shared
	# helper as get_digital_marketing_dashboard's campaign_cost_data (so the
	# two views can't diverge), but unscoped by digital-source-only leads,
	# since a Director needs the whole funnel, not just the digital slice.
	campaign_list = frappe.db.get_all("CRM Campaign", fields=["name", "title"], limit=10)
	campaign_cost_data = _campaign_cost_data(campaign_list, from_date, to_date, base_filters)

	# One bounded Student query + batched evidence reads; this avoids the former
	# per-Contact attribution call (and does not depend on Contact permission).
	scoped_contacts = set(frappe.get_list("CRM Contact", filters=base_filters, pluck="name", limit_page_length=0))
	scoped_student_names = {
		student
		for contact in scoped_contacts
		for student in students_for_contact(contact)
	}
	enrolled_students = frappe.get_list(
		"CRM Student",
		filters={
			"name": ["in", list(scoped_student_names) or ["__none__"]],
			"enrollment_status": "Đã nhập học",
		},
		pluck="name",
		limit_page_length=200,
	)
	multi_touch_credit_by_campaign = get_equal_credit_by_campaign_for_students(enrolled_students)
	multi_touch_data = [
		{"campaign": frappe.db.get_value("CRM Campaign", name, "title") or name, "credit": round(credit, 2)}
		for name, credit in sorted(multi_touch_credit_by_campaign.items(), key=lambda kv: kv[1], reverse=True)[:10]
	]

	items = [
		{"name": "director_total_leads", "type": "number_chart", "layout": {"x": 0, "y": 0, "w": 4, "h": 3, "i": "director_total_leads"}, "data": {"title": "Tổng Lead", "tooltip": "Tổng số Lead trong kỳ, mọi kênh", "value": total_leads, "delta": 0.0, "deltaSuffix": "%"}},
		{"name": "director_qualified_rate", "type": "number_chart", "layout": {"x": 4, "y": 0, "w": 4, "h": 3, "i": "director_qualified_rate"}, "data": {"title": "Qualified Rate (%)", "tooltip": "Tỷ lệ Lead đủ điều kiện", "value": qualified_rate, "delta": 0.0, "deltaSuffix": "%"}},
		{"name": "director_conversion_rate", "type": "number_chart", "layout": {"x": 8, "y": 0, "w": 4, "h": 3, "i": "director_conversion_rate"}, "data": {"title": "Conversion Rate (%)", "tooltip": "Tỷ lệ Lead nhập học", "value": conversion_rate, "delta": 0.0, "deltaSuffix": "%"}},
		{"name": "director_total_spend", "type": "number_chart", "layout": {"x": 12, "y": 0, "w": 4, "h": 3, "i": "director_total_spend"}, "data": {"title": "Tổng chi phí (triệu)", "tooltip": "Tổng chi phí marketing trong kỳ, mọi chiến dịch", "value": round(total_spend / 1000000, 1), "delta": 0.0, "deltaSuffix": "%"}},
		{"name": "director_cost_enrollment", "type": "number_chart", "layout": {"x": 16, "y": 0, "w": 4, "h": 3, "i": "director_cost_enrollment"}, "data": {"title": "Chi phí / Enrollment (triệu)", "tooltip": "Chi phí trung bình trên mỗi enrollment, mọi chiến dịch", "value": cost_per_enrollment, "delta": 0.0, "deltaSuffix": "%"}},
		{
			"name": "director_campaign_cost",
			"type": "axis_chart",
			"layout": {"x": 0, "y": 3, "w": 12, "h": 8, "i": "director_campaign_cost"},
			"data": {
				"data": campaign_cost_data,
				"title": "Chi phí / Chuyển đổi theo chiến dịch (Last-touch)",
				"subtitle": "Toàn bộ chiến dịch, không giới hạn nguồn Digital",
				"xAxis": {"title": "", "key": "campaign", "type": "category"},
				"yAxis": {"title": "Giá trị"},
				"series": [
					{"name": "spend", "type": "bar"},
					{"name": "attributedConversions", "type": "bar"},
					{"name": "costPerConversion", "type": "bar"},
				],
			},
		},
		{
			"name": "director_multi_touch_credit",
			"type": "axis_chart",
			"layout": {"x": 12, "y": 3, "w": 8, "h": 8, "i": "director_multi_touch_credit"},
			"data": {
				"data": multi_touch_data,
				"title": "Multi-touch Credit theo chiến dịch",
				"subtitle": "Đối chiếu Last-touch: credit chia đều cho mọi touchpoint của Lead đã nhập học",
				"xAxis": {"title": "", "key": "campaign", "type": "category"},
				"yAxis": {"title": "Credit"},
				"series": [{"name": "credit", "type": "bar"}],
			},
		},
	]

	return items
