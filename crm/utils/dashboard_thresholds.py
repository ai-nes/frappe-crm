# Shared lead-temperature thresholds for the Sale / Offline Marketing dashboards.
# Tunable by editing this constant only — no in-app CRUD UI in v1.

SCORE_THRESHOLDS = {
	"hot": 70,  # CRM Student.latest_score >= 70
	"warm": 40,  # 40 <= latest_score < 70
	# below 40 == "cool"
}


def score_to_bucket(score):
	if score is None:
		return None
	if score >= SCORE_THRESHOLDS["hot"]:
		return "hot"
	if score >= SCORE_THRESHOLDS["warm"]:
		return "warm"
	return "cool"
