import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

import app as app_module
from manage_store import ManageStore


class PaypalManageBillingTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.previous_store = app_module.MANAGE_STORE
        self.previous_password = app_module.MANAGE_PASSWORD
        app_module.MANAGE_STORE = ManageStore(root / "manage.sqlite3", Fernet.generate_key())
        app_module.MANAGE_PASSWORD = "test-password"
        app_module.app.config["TESTING"] = True
        self.profile = app_module.MANAGE_STORE.upsert_billing_profile({
            "profile_key": "paypal:GB:primary",
            "rail": "paypal",
            "country": "GB",
            "name": "Private Billing Holder",
            "email": "private@example.test",
            "line1": "77 Private Billing Lane",
            "line2": "Suite 8",
            "city": "London",
            "state": "England",
            "postal_code": "SW1A 1AA",
        })
        self.client = app_module.app.test_client()

    def tearDown(self):
        app_module.MANAGE_STORE = self.previous_store
        app_module.MANAGE_PASSWORD = self.previous_password
        self.tempdir.cleanup()

    def login(self, client=None):
        response = (client or self.client).post(
            "/api/manage/login",
            json={"password": "test-password"},
        )
        self.assertEqual(response.status_code, 200)

    @staticmethod
    def checkout_payload(selection):
        return {
            "token": "test-access-token",
            "plan": "plus",
            "link_type": "paypal",
            "country": "US",
            "currency": "USD",
            "entry_proxies": ["http://user:pass@127.0.0.1:18080"],
            "exit_proxies": ["http://user:pass@127.0.0.1:18081"],
            "billing_selection": selection,
        }

    def test_options_require_login_and_keep_manual_profiles_masked(self):
        self.assertEqual(
            self.client.get("/api/manage/paypal-billing-options?country=GB").status_code,
            401,
        )
        self.login()

        response = self.client.get("/api/manage/paypal-billing-options?country=GB")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["country"], "GB")
        self.assertTrue(any(item["country"] == "GB" for item in payload["countries"]))

        manual = next(item for item in payload["manual_profiles"] if item["id"] == self.profile["id"])
        self.assertEqual(manual["profile_key"], "paypal:GB:primary")
        self.assertTrue(manual["address_masked"])
        self.assertNotEqual(manual["address_masked"], "77 Private Billing Lane")
        self.assertNotIn("profile", manual)
        self.assertNotIn("77 Private Billing Lane", json.dumps(payload, ensure_ascii=False))

        self.assertGreater(len(payload["builtin_addresses"]), 0)
        builtin = payload["builtin_addresses"][0]
        self.assertRegex(builtin["id"], r"^[0-9a-f]{20}$")
        repeated = self.client.get("/api/manage/paypal-billing-options?country=GB").get_json()
        self.assertEqual(repeated["builtin_addresses"][0]["id"], builtin["id"])

    def test_checkout_resolves_selected_profile_server_side(self):
        self.login()
        captured = {}

        def capture(options):
            captured.clear()
            captured.update(options)
            return "job-paypal-billing"

        with (
            patch.object(app_module.STORE, "create", side_effect=capture),
            patch.object(app_module.STORE, "queue_position", return_value=0),
            patch.object(app_module.IP_TASK_LIMITER, "acquire", return_value=(True, 0)),
        ):
            response = self.client.post(
                "/api/checkout",
                json=self.checkout_payload({
                    "kind": "manage_profile",
                    "id": self.profile["id"],
                    "country": "GB",
                }),
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(captured["paypal_billing_profile"]["line1"], "77 Private Billing Lane")
        self.assertEqual(captured["paypal_billing_profile"]["country"], "GB")
        self.assertEqual(captured["paypal_billing_selection"]["kind"], "manage_profile")
        self.assertEqual(captured["billing_profile"], {})

        anonymous = app_module.app.test_client()
        denied = anonymous.post(
            "/api/checkout",
            json=self.checkout_payload({
                "kind": "manage_profile",
                "id": self.profile["id"],
                "country": "GB",
            }),
        )
        self.assertEqual(denied.status_code, 401)
        self.assertIn("登录管理中心", denied.get_json()["error"])

    def test_protocol_detection_is_a_separate_fixed_de_job_without_promo(self):
        captured = {}

        def capture(options):
            captured.clear()
            captured.update(options)
            return "job-paypal-detect"

        with (
            patch.object(app_module.STORE, "create", side_effect=capture),
            patch.object(app_module.STORE, "queue_position", return_value=0),
            patch.object(app_module.IP_TASK_LIMITER, "acquire", return_value=(True, 0)),
        ):
            response = self.client.post(
                "/api/checkout-detect",
                json=self.checkout_payload(None),
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json()["mode"], "protocol_detection")
        self.assertTrue(captured["detection_only"])
        self.assertTrue(captured["detection_fixed_de"])
        self.assertFalse(captured["use_promo"])
        self.assertEqual(captured["checkout_country"], "DE")
        self.assertEqual(captured["checkout_currency"], "EUR")

    def test_checkout_resolves_exact_builtin_address_by_stable_id(self):
        self.login()
        listing = self.client.get("/api/manage/paypal-billing-options?country=GB").get_json()
        chosen = next(item for item in listing["builtin_addresses"] if item["name"] == "The Savoy")
        captured = {}

        with (
            patch.object(app_module.STORE, "create", side_effect=lambda options: captured.update(options) or "job-builtin"),
            patch.object(app_module.STORE, "queue_position", return_value=0),
            patch.object(app_module.IP_TASK_LIMITER, "acquire", return_value=(True, 0)),
        ):
            response = self.client.post(
                "/api/checkout",
                json=self.checkout_payload({
                    "kind": "builtin_address",
                    "id": chosen["id"],
                    "country": "GB",
                }),
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(captured["paypal_billing_profile"]["name"], "The Savoy")
        self.assertEqual(captured["paypal_billing_profile"]["line1"], "Strand")
        self.assertEqual(captured["paypal_billing_selection"]["kind"], "builtin_address")

    def test_runtime_target_country_matches_paypal_billing_behavior(self):
        self.assertEqual(app_module.paypal_billing_target_country("GB", "GB"), "GB")
        self.assertEqual(app_module.paypal_billing_target_country("DE", "GB"), "GB")
        self.assertEqual(app_module.paypal_billing_target_country("DE", "BR"), "BR")
        self.assertEqual(app_module.paypal_billing_target_country("DE", "TH"), "TH")
        self.assertEqual(app_module.paypal_billing_target_country("DE", "JP"), "JP")
        self.assertEqual(app_module.paypal_billing_target_country("DE", "AU"), "AU")
        self.assertEqual(app_module.paypal_billing_target_country("DE", "SG"), "DE")
        self.assertEqual(
            app_module.paypal_billing_target_country(
                "DE", "GB", force_checkout_country=True,
            ),
            "DE",
        )

    def test_new_paypal_regions_keep_native_checkout_currency(self):
        for country, currency in (("BR", "BRL"), ("TH", "THB"), ("JP", "JPY"), ("AU", "AUD")):
            checkout_country, checkout_currency, _ = app_module.normalize_paypal_checkout_region(
                country,
                currency,
            )
            self.assertEqual((checkout_country, checkout_currency), (country, currency))

        checkout_country, checkout_currency, _ = app_module.normalize_paypal_checkout_region("SG", "SGD")
        self.assertEqual((checkout_country, checkout_currency), ("DE", "EUR"))


if __name__ == "__main__":
    unittest.main()
