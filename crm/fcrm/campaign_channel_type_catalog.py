"""Canonical campaign channel type catalog used by migrations and APIs."""

from __future__ import annotations

from typing import Final

CAMPAIGN_CHANNEL_TYPE_CATALOG: Final[tuple[tuple[str, str, tuple[str, ...]], ...]] = (
	("FACEBOOK_LEAD_FORM", "Facebook Lead Form", ("ONLINE",)),
	("TIKTOK_LEAD_FORM", "TikTok Lead Form", ("ONLINE",)),
	("GOOGLE_LEAD_FORM", "Google Lead Form", ("ONLINE",)),
	("ZALO_LEAD_FORM", "Zalo Lead Form", ("ONLINE",)),
	("FACEBOOK_LANDING_PAGE", "Facebook Lead Landing Page", ("ONLINE",)),
	("GOOGLE_SEARCH_ADS_LANDING_PAGE", "Google Search Ads Landing Page", ("ONLINE",)),
	("TIKTOK_LANDING_PAGE", "TikTok Lead Landing Page", ("ONLINE",)),
	("ZALO_LANDING_PAGE", "Zalo Lead Landing Page", ("ONLINE",)),
	("HOTLINE", "Tổng đài", ("ONLINE",)),
	("WEBSITE_DAIHOC_MARCOM", "Website Đại học - Marcom", ("ONLINE",)),
	("CRM_IT_HO", "CRM IT HO", ("ONLINE",)),
	("CLASS_COUNSELING", "Tư vấn lớp", ("OFFLINE",)),
	("OPEN_DAY", "Open Day", ("OFFLINE",)),
	("EXPERIENCE_DAY", "Experience Day", ("OFFLINE",)),
	("HIGH_SCHOOL_GENERAL_COUNSELING", "Tư vấn chung ở trường THPT", ("OFFLINE",)),
	("COUNSELING_BOOTH", "Đặt bàn tư vấn", ("OFFLINE",)),
	("HIGH_SCHOOL_SEMINAR", "Chuyên đề tại trường THPT", ("OFFLINE",)),
	("ADMISSION_COUNSELING_PROGRAM", "Chương trình tư vấn tuyển sinh", ("OFFLINE",)),
	("CAREER_COUNSELING_PROGRAM", "Chương trình tư vấn hướng nghiệp", ("OFFLINE",)),
	("PARENT_SEMINAR", "Hội thảo PHHS", ("OFFLINE",)),
	("PARENT_COUNSELING_DAY", "Ngày hội tư vấn PHHS", ("OFFLINE",)),
	("CAMPUS_DIRECT_COUNSELING", "Tư vấn tuyển sinh trực tiếp tại campus", ("OFFLINE",)),
	("REFERRAL", "Giới thiệu", ("ONLINE", "OFFLINE")),
	("OTHER", "Khác", ("ONLINE", "OFFLINE")),
)

CAMPAIGN_CHANNEL_TYPE_CODES: Final[frozenset[str]] = frozenset(
	row[0] for row in CAMPAIGN_CHANNEL_TYPE_CATALOG
)
CAMPAIGN_CHANNEL_TYPE_MODES: Final[frozenset[str]] = frozenset(
	mode for _, _, modes in CAMPAIGN_CHANNEL_TYPE_CATALOG for mode in modes
)
