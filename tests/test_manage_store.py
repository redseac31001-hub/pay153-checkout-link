import json
import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from manage_store import ManageStore


class ManageStoreTests(unittest.TestCase):
    def make_store(self, root: str, legacy: str | None = None) -> ManageStore:
        return ManageStore(Path(root) / "manage.sqlite3", Fernet.generate_key(), legacy)

    def test_proxy_and_billing_sensitive_values_are_encrypted_and_masked(self):
        with tempfile.TemporaryDirectory() as root:
            store = self.make_store(root)
            proxy = store.upsert_proxy_pool({
                "external_key": "test:gopay:exit",
                "name": "Gopay ID",
                "rail": "gopay",
                "country": "ID",
                "pool_kind": "exit",
                "proxies": ["http://proxy-user:proxy-password@example.test:8080"],
            })
            self.assertEqual(proxy["proxy_count"], 1)
            self.assertIn("***:***@example.test:8080", proxy["proxy_preview"][0])
            revealed_proxy = store.get_proxy_pool(proxy["id"], reveal=True)
            self.assertEqual(revealed_proxy["proxies"][0], "http://proxy-user:proxy-password@example.test:8080")
            updated_proxy = store.upsert_proxy_pool({
                "id": proxy["id"], "external_key": "test:gopay:exit:v2", "name": "Gopay ID v2",
                "rail": "gopay", "country": "ID", "pool_kind": "exit",
                "proxies": ["http://proxy-user:new-password@example.test:8080"],
            })
            self.assertEqual(updated_proxy["name"], "Gopay ID v2")
            self.assertEqual(store.get_proxy_pool(proxy["id"], reveal=True)["proxies"][0], "http://proxy-user:new-password@example.test:8080")

            billing = store.upsert_billing_profile({
                "profile_key": "gopay:ID",
                "rail": "gopay",
                "country": "ID",
                "name": "Example Billing",
                "email": "billing@example.test",
                "line1": "1 Example Street",
                "city": "Jakarta",
                "postal_code": "10110",
            })
            self.assertEqual(billing["email_masked"], "bi***@example.test")
            revealed_billing = store.get_billing_profile(billing["id"], reveal=True)
            self.assertEqual(revealed_billing["profile"]["line1"], "1 Example Street")
            renamed_billing = store.upsert_billing_profile({
                "id": billing["id"], "profile_key": "gopay:ID:primary", "rail": "gopay", "country": "ID",
                "name": "Updated Billing", "line1": "2 Example Street", "city": "Jakarta", "postal_code": "10110",
            })
            self.assertEqual(renamed_billing["profile_key"], "gopay:ID:primary")

            raw_db = Path(root, "manage.sqlite3").read_bytes()
            self.assertNotIn(b"proxy-password", raw_db)
            self.assertNotIn(b"1 Example Street", raw_db)

    def test_asn_order_and_success_records(self):
        with tempfile.TemporaryDirectory() as root:
            store = self.make_store(root)
            store.seed_asn_recommendations({"GB": {"label": "英国", "items": ["AS5607", "AS2856"]}})
            recommendations = store.list_asn_recommendations("GB")
            self.assertEqual([item["asn"] for item in recommendations[0]["items"]], ["AS5607", "AS2856"])

            result = store.record_success({
                "job_id": "job-success-1",
                "recorded_at": "2026-08-10 12:00:00",
                "plan": "plus",
                "link_type": "gopay",
                "country": "ID",
                "currency": "IDR",
                "account_email": "person@example.test",
                "account_id": "acct_1234567890",
                "entry_ip": "203.0.113.10",
                "entry_country": "TH",
                "entry_region": "Bangkok",
                "payment_ip": "203.0.113.20",
                "payment_proxy_country": "ID",
                "payment_region": "Jakarta",
                "checkout_amount": "0",
                "url": "https://pay.example.test/secret-link",
            })
            self.assertEqual(result["account"], "pe***@example.test")
            self.assertEqual(result["entry_ip"], "203.0.113.*")
            self.assertEqual(result["payment_ip"], "203.0.113.*")
            self.assertNotIn("secret-link", json.dumps(result))
            revealed = store.get_success_by_job("job-success-1")
            self.assertEqual(revealed["entry_ip"], "203.0.113.*")

    def test_legacy_success_import_is_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            legacy_path = Path(root, "success_links.jsonl")
            legacy_path.write_text(json.dumps({
                "job_id": "legacy-job-1",
                "recorded_at": "2026-08-10 12:00:00",
                "link_type": "gopay",
                "account_email": "legacy@example.test",
                "url": "https://pay.example.test/legacy",
            }) + "\n", encoding="utf-8")
            first = self.make_store(root, legacy_path)
            self.assertEqual(first.get_success_by_job("legacy-job-1")["job_id"], "legacy-job-1")
            second = self.make_store(root, legacy_path)
            self.assertEqual(second.summary()["success_records"], 1)

    def test_oaics_fallback_is_encrypted_and_can_be_finalized(self):
        with tempfile.TemporaryDirectory() as root:
            store = self.make_store(root)
            store.record_oaics_fallback({
                "job_id": "job-oaics-1",
                "recorded_at": "2026-08-12 12:00:00",
                "status": "pending",
                "link_type": "paypal",
                "plan": "plus",
                "country": "BR",
                "currency": "BRL",
                "account_email": "person@example.test",
                "account_id": "acct_oaics_123",
                "session_id": "oaics_sensitive_session",
                "processor_entity": "openai_llc",
                "payment_methods": ["link", "card"],
                "url": "https://chatgpt.com/checkout/openai_llc/oaics_sensitive_session",
                "attempt": 1,
                "max_attempts": 3,
            })

            pending = store.get_oaics_fallback_by_job("job-oaics-1", reveal=True)
            self.assertEqual(pending["status"], "pending")
            self.assertEqual(pending["url"], "https://chatgpt.com/checkout/openai_llc/oaics_sensitive_session")
            self.assertEqual(pending["session_id"], "oaics_sensitive_session")
            self.assertEqual(pending["payment_methods"], ["link", "card"])

            store.finalize_oaics_fallback("job-oaics-1", "superseded", "cs_live_final")
            finalized = store.get_oaics_fallback_by_job("job-oaics-1", reveal=True)
            self.assertEqual(finalized["status"], "superseded")
            self.assertEqual(finalized["resolved_session_id"], "cs_live_final")

            raw_db = Path(root, "manage.sqlite3").read_bytes()
            self.assertNotIn(b"oaics_sensitive_session", raw_db)
            self.assertNotIn(b"https://chatgpt.com/checkout", raw_db)


if __name__ == "__main__":
    unittest.main()
