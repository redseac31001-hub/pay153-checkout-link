import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

import app as app_module
from manage_store import ManageStore


class ManageApiTests(unittest.TestCase):
    def test_management_requires_login_and_supports_core_resources(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            previous_store = app_module.MANAGE_STORE
            previous_password = app_module.MANAGE_PASSWORD
            previous_log_dir = app_module.BACKEND_LOG_DIR
            app_module.MANAGE_STORE = ManageStore(root_path / "manage.sqlite3", Fernet.generate_key())
            app_module.MANAGE_PASSWORD = "test-password"
            app_module.BACKEND_LOG_DIR = root_path / "logs"
            app_module.app.config["TESTING"] = True
            try:
                client = app_module.app.test_client()
                manage_page = client.get("/manage")
                self.assertEqual(manage_page.status_code, 200)
                manage_page.close()
                self.assertFalse(client.get("/api/manage/session").get_json()["authenticated"])
                self.assertEqual(client.get("/api/manage/summary").status_code, 401)
                self.assertEqual(client.post("/api/manage/login", json={"password": "wrong"}).status_code, 401)
                self.assertEqual(client.post("/api/manage/login", json={"password": "test-password"}).status_code, 200)

                self.assertEqual(client.get("/api/manage/summary").status_code, 200)
                address_listing = client.get("/api/manage/builtin-addresses").get_json()
                savoy = next(
                    item for item in address_listing["addresses"]
                    if item["country"] == "GB" and item["name"] == "The Savoy"
                )
                self.assertEqual(savoy["line1"], "Strand")
                self.assertEqual(savoy["type"], "office")
                self.assertEqual(savoy["source"], "builtin_public")
                self.assertEqual(address_listing["total"], len(address_listing["addresses"]))
                self.assertGreaterEqual(address_listing["library_total"], 400)
                self.assertIn("GB", address_listing["countries"])

                created_proxy = client.post("/api/manage/proxy-pools", json={
                    "name": "Gopay ID",
                    "rail": "gopay",
                    "country": "ID",
                    "pool_kind": "exit",
                    "proxies": ["http://user:pass@example.test:8080"],
                })
                self.assertEqual(created_proxy.status_code, 201)
                proxy = created_proxy.get_json()["item"]
                self.assertNotIn("user:pass", str(proxy))
                revealed = client.get(f"/api/manage/proxy-pools/{proxy['id']}?reveal=1").get_json()
                self.assertEqual(revealed["proxies"][0], "http://user:pass@example.test:8080")

                billing = client.post("/api/manage/billing-profiles", json={
                    "profile_key": "gopay:ID",
                    "rail": "gopay",
                    "country": "ID",
                    "name": "Example",
                    "email": "example@test.invalid",
                    "line1": "1 Main Street",
                    "city": "Jakarta",
                    "postal_code": "10110",
                })
                self.assertEqual(billing.status_code, 201)
                self.assertNotIn("1 Main Street", billing.get_data(as_text=True))

                asn = client.put("/api/manage/asn-recommendations", json={
                    "country": "GB", "label": "英国", "items": ["AS2856", "AS5607"]
                })
                self.assertEqual(asn.status_code, 200)
                self.assertEqual(len(client.get("/api/manage/asn-recommendations?country=GB").get_json()["items"]), 1)

                log_path = app_module.BACKEND_LOG_DIR / "2026-08-10" / "job-test.log"
                log_path.parent.mkdir(parents=True)
                log_path.write_text("2026-08-10 12:00:00 [STATUS] Gopay 完成 Bearer secret-token\n", encoding="utf-8")
                logs = client.get("/api/manage/logs?day=2026-08-10").get_json()["items"]
                self.assertEqual(logs[0]["message"], "Gopay 完成 Bearer [TOKEN]")

                imported = client.post("/api/manage/import-local", json={
                    "proxy_profiles": {"profiles": {"paypal": {"entry": "http://u:p@example.test:8081"}}},
                    "billing_profiles": {"profiles": {"paypal:GB": {"name": "Imported", "line1": "Imported Street", "city": "London", "postal_code": "SW1A"}}},
                    "asn_recommendations": {"regions": {"GB": {"label": "英国", "items": [{"asn": "AS13037"}]}}},
                })
                self.assertEqual(imported.status_code, 200)
                self.assertEqual(imported.get_json()["imported"]["proxy_pools"], 1)
                self.assertEqual(client.post("/api/manage/logout").status_code, 200)
                self.assertEqual(client.get("/api/manage/summary").status_code, 401)
            finally:
                app_module.MANAGE_STORE = previous_store
                app_module.MANAGE_PASSWORD = previous_password
                app_module.BACKEND_LOG_DIR = previous_log_dir


if __name__ == "__main__":
    unittest.main()
