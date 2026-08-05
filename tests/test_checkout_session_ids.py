import unittest
from unittest.mock import patch

import app


class _Cookies:
    def set(self, *_args, **_kwargs):
        return None


class _Response:
    status_code = 200
    text = '{"checkout_session_id":"oaics_test_internal","url":"https://pay.openai.com/c/pay/cs_live_expected"}'

    def json(self):
        return {
            "checkout_session_id": "oaics_test_internal",
            "url": "https://pay.openai.com/c/pay/cs_live_expected",
        }


class _Http:
    def __init__(self):
        self.cookies = _Cookies()

    def get(self, *_args, **_kwargs):
        return _Response()

    def post(self, *_args, **_kwargs):
        return _Response()


class CheckoutSessionIdTests(unittest.TestCase):
    def test_stripe_id_wins_over_openai_id_in_url(self):
        payload = {
            "checkout_session_id": "oaics_test_internal",
            "url": "https://pay.openai.com/c/pay/cs_live_expected",
        }
        self.assertEqual(
            app.extract_stripe_checkout_session_id(payload),
            "cs_live_expected",
        )

    def test_nested_checkout_session_id_is_supported(self):
        payload = {
            "checkout_session_id": "oaics_test_internal",
            "checkout_session": {
                "checkout_session_id": "cs_live_nested",
            },
        }
        self.assertEqual(
            app.extract_stripe_checkout_session_id(payload),
            "cs_live_nested",
        )

    def test_non_stripe_id_is_not_accepted_as_payment_page(self):
        self.assertEqual(
            app.extract_stripe_checkout_session_id(
                {"checkout_session_id": "oaics_test_internal"}
            ),
            "",
        )

    def test_create_checkout_stores_stripe_id_when_top_level_id_is_oaics(self):
        async def fake_sentinel(*_args, **_kwargs):
            return {}

        with patch.object(app.sc, "build_http", return_value=_Http()), patch.object(
            app, "sentinel_headers", side_effect=fake_sentinel
        ):
            result = app.create_checkout(
                "token",
                {},
                "",
                "device",
                "did",
                lambda _message: None,
            )

        self.assertEqual(result["data"]["checkout_session_id"], "cs_live_expected")
        self.assertEqual(result["data"]["openai_checkout_session_id"], "oaics_test_internal")


if __name__ == "__main__":
    unittest.main()
