import unittest

from provider_checkout import default_billing, normalize_billing_profile


class BillingProfileTests(unittest.TestCase):
    def setUp(self):
        self.profile = {
            "country": "ID",
            "name": "Verified Customer",
            "email": "customer@example.com",
            "line1": "Jl. Example No. 10",
            "line2": "Unit 2",
            "city": "Jakarta",
            "state": "Jakarta",
            "postal_code": "10110",
        }

    def test_profile_is_country_bound_and_normalized(self):
        result = normalize_billing_profile(self.profile, "ID", require_complete=True)
        self.assertEqual(result["country"], "ID")
        self.assertEqual(result["line1"], "Jl. Example No. 10")
        self.assertEqual(result["postal_code"], "10110")

    def test_country_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "国家"):
            normalize_billing_profile(self.profile, "US", require_complete=True)

    def test_gopay_requires_a_complete_profile(self):
        with self.assertRaisesRegex(ValueError, "账单地址档案"):
            default_billing("ID", "customer@example.com", require_profile=True)

    def test_manual_profile_wins_over_static_defaults(self):
        billing = default_billing(
            "ID",
            "fallback@example.com",
            billing_profile=self.profile,
            require_profile=True,
        )
        self.assertEqual(billing["_address_source"], "manual_profile")
        self.assertEqual(billing["email"], "customer@example.com")
        self.assertEqual(billing["address"]["country"], "ID")
        self.assertEqual(billing["address"]["city"], "Jakarta")
        self.assertEqual(billing["address"]["line2"], "Unit 2")

    def test_empty_profile_uses_automatic_complete_address(self):
        billing = default_billing(
            "DE",
            "customer@example.com",
            billing_profile={},
            real_random=False,
        )
        self.assertNotEqual(billing["_address_source"], "manual_profile")
        self.assertTrue(billing["address"]["city"])
        self.assertTrue(billing["address"]["postal_code"])


if __name__ == "__main__":
    unittest.main()
