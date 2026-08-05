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


class _OaicsResponse:
    status_code = 200
    text = '{"checkout_session_id":"oaics_test_internal","processor_entity":"openai_ie"}'

    def json(self):
        return {
            "checkout_session_id": "oaics_test_internal",
            "processor_entity": "openai_ie",
        }


class _OaicsHttp(_Http):
    def get(self, *_args, **_kwargs):
        return _OaicsResponse()

    def post(self, *_args, **_kwargs):
        return _OaicsResponse()


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

    def test_checkout_response_summary_keeps_schema_but_redacts_values(self):
        summary = app.summarize_checkout_response({
            "checkout_session": {
                "checkout_session_id": "oaics_sensitive_session",
                "publishable_key": "pk_live_sensitive_key",
                "url": "https://pay.openai.com/c/pay/oaics_sensitive_session",
            },
            "client_secret": "cs_secret_value",
        })

        self.assertIn("checkout_session.checkout_session_id=oaics_*", summary)
        self.assertIn("checkout_session.publishable_key=<redacted>", summary)
        self.assertIn("checkout_session.url=<url>", summary)
        self.assertNotIn("oaics_sensitive_session", summary)
        self.assertNotIn("pk_live_sensitive_key", summary)
        self.assertNotIn("cs_secret_value", summary)

    def test_oaics_contract_error_is_non_retryable(self):
        error = app.CheckoutSessionContractError("test")
        self.assertEqual(
            error.error_code,
            app.CHECKOUT_SESSION_CONTRACT_ERROR_CODE,
        )

    def test_oaics_session_uses_openai_managed_checkout_url(self):
        async def fake_sentinel(*_args, **_kwargs):
            return {}

        with patch.object(app.sc, "build_http", return_value=_OaicsHttp()), patch.object(
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

        self.assertEqual(result["data"]["checkout_session_id"], "oaics_test_internal")
        self.assertEqual(
            result["data"]["checkout_url"],
            "https://chatgpt.com/checkout/openai_ie/oaics_test_internal",
        )


if __name__ == "__main__":
    unittest.main()
