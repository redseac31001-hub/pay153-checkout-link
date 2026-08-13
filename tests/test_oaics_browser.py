import unittest

from oaics_browser import (
    ChainedHttpProxy,
    extract_paypal_ba_url,
    validate_paypal_ba_url,
)


class OaicsBrowserTests(unittest.TestCase):
    def test_ba_url_requires_paypal_host_and_ba_token(self):
        self.assertTrue(
            validate_paypal_ba_url(
                "https://www.paypal.com/agreements/approve?ba_token=BA-test_123"
            )
        )
        self.assertFalse(
            validate_paypal_ba_url(
                "https://evil.paypal.com/agreements/approve?ba_token=BA-test_123"
            )
        )
        self.assertFalse(
            validate_paypal_ba_url(
                "https://www.paypal.com/agreements/approve?token=BA-test_123"
            )
        )

    def test_extracts_ba_url_from_nested_response(self):
        value = {
            "redirect": {
                "url": "https://www.paypal.com/agreements/approve?ba_token=BA-abc_123&country.x=DE"
            }
        }
        self.assertEqual(
            extract_paypal_ba_url(value),
            "https://www.paypal.com/agreements/approve?ba_token=BA-abc_123&country.x=DE",
        )

    def test_blocked_response_does_not_look_like_ba(self):
        self.assertEqual(extract_paypal_ba_url({"status": "blocked"}), "")

    def test_browser_relay_binds_loopback_and_stops(self):
        relay = ChainedHttpProxy(
            "http://127.0.0.1:8080",
            "socks5://127.0.0.1:9697",
        )
        address = relay.start()
        try:
            self.assertTrue(address.startswith("http://127.0.0.1:"))
        finally:
            relay.stop()


if __name__ == "__main__":
    unittest.main()
