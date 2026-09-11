from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import google_auth


class TestGoogleAuth(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_safe_redirect_rejects_external_urls(self):
		self.assertEqual(google_auth._safe_redirect_to("https://evil.example"), "/crm")
		self.assertEqual(google_auth._safe_redirect_to("//evil.example"), "/crm")
		self.assertEqual(google_auth._safe_redirect_to("/app"), "/app")

	def test_safe_redirect_allows_configured_dashboard_url(self):
		config = {"dashboard_url": ["http://localhost:5000"]}
		with patch.object(google_auth, "_config", return_value=config):
			self.assertEqual(
				google_auth._safe_redirect_to("http://localhost:5000/auth/callback"),
				"http://localhost:5000/auth/callback",
			)
			self.assertEqual(google_auth._safe_redirect_to("http://localhost:5000"), "http://localhost:5000")
			# A different origin that only shares a prefix must not pass.
			self.assertEqual(google_auth._safe_redirect_to("http://localhost:5000.evil.example"), "/crm")
			self.assertEqual(google_auth._safe_redirect_to("http://evil.example"), "/crm")

	@patch.object(google_auth.frappe, "generate_hash", return_value="state-token")
	@patch.object(google_auth.frappe.cache, "set_value")
	def test_login_redirects_to_google(self, _set_value, _generate_hash):
		config = {"client_id": "client-id", "client_secret": "client-secret"}
		frappe.local.response = frappe._dict()
		with patch.object(google_auth, "_config", return_value=config), patch.object(
			google_auth, "_redirect_uri", return_value="http://crm.localhost/api/method/crm.api.google_auth.callback"
		):
			google_auth.login("http://localhost:5000/auth/callback")

		self.assertEqual(frappe.local.response["type"], "redirect")
		self.assertTrue(frappe.local.response["location"].startswith(google_auth.GOOGLE_AUTHORIZE_URL))

	@patch.object(google_auth.frappe, "generate_hash", return_value="state-token")
	@patch.object(google_auth.frappe.cache, "set_value")
	def test_authorize_url_uses_crm_config_and_callback(self, set_value, _generate_hash):
		config = {
			"client_id": "client-id",
			"client_secret": "client-secret",
			"redirect_uri": "http://crm.localhost/api/method/crm.api.google_auth.callback",
		}
		with patch.object(google_auth, "_config", return_value=config):
			url = google_auth._authorize_url("/crm")

		query = parse_qs(urlparse(url).query)
		self.assertEqual(query["client_id"], ["client-id"])
		self.assertEqual(query["redirect_uri"], [config["redirect_uri"]])
		self.assertEqual(query["state"], ["state-token"])
		self.assertEqual(query["scope"], ["openid email profile"])
		set_value.assert_called_once()

	@patch.object(google_auth.requests, "get")
	def test_fetch_google_identity_requires_verified_email(self, get):
		response = MagicMock(status_code=200)
		response.json.return_value = {"sub": "google-sub", "email": "person@example.com", "email_verified": False}
		get.return_value = response

		with self.assertRaises(frappe.AuthenticationError):
			google_auth._fetch_google_identity("access-token")

	@patch.object(google_auth, "_config", return_value={"default_role": "Sale"})
	def test_new_google_user_is_system_user_with_configured_crm_role(self, _config):
		email = "_test_google_auth@example.com"
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True)

		try:
			user = google_auth._get_or_create_crm_user(
				{
					"email": email,
					"sub": "google-sub",
					"given_name": "Google",
					"family_name": "User",
				}
			)
			self.assertEqual(user.user_type, "System User")
			self.assertIn("Sale", frappe.get_roles(user.name))
		finally:
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, force=True)

	@patch.object(google_auth, "_config", return_value={"default_role": "Business Admin"})
	def test_business_admin_cannot_be_google_oauth_default_role(self, _config):
		with self.assertRaises(frappe.ValidationError):
			google_auth._default_role()
