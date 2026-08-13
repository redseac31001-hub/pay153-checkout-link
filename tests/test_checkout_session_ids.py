import time
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
    def test_oaics_billing_is_fixed_to_de_and_ignores_non_de_profile(self):
        captured = {}

        def fake_default_billing(country, email, **kwargs):
            captured.update({"country": country, "email": email, **kwargs})
            return {"address": {"country": country}}

        with patch.object(app, "default_billing", side_effect=fake_default_billing):
            country, billing = app.build_oaics_billing(
                "oaics@example.test",
                billing_profile={"country": "BR", "city": "Sao Paulo"},
            )

        self.assertEqual(country, "DE")
        self.assertEqual(billing["address"]["country"], "DE")
        self.assertEqual(captured["country"], "DE")
        self.assertEqual(captured["email"], "oaics@example.test")
        self.assertIsNone(captured["geo"])
        self.assertIsNone(captured["billing_profile"])
        self.assertTrue(captured["real_random"])

    def test_checkout_protocol_classification_prefers_stripe_session(self):
        self.assertEqual(
            app.checkout_protocol_from_payload({
                "checkout_session_id": "oaics_test_internal",
                "url": "https://pay.openai.com/c/pay/cs_live_expected",
            }),
            app.CHECKOUT_PROTOCOL_CS,
        )
        self.assertEqual(
            app.checkout_protocol_from_payload({
                "checkout_session_id": "oaics_test_internal",
            }),
            app.CHECKOUT_PROTOCOL_OAICS,
        )
        self.assertEqual(
            app.checkout_protocol_from_payload({"checkout_session_id": "unknown"}),
            app.CHECKOUT_PROTOCOL_UNKNOWN,
        )

    def test_checkout_protocol_hint_requires_fresh_matching_or_de_baseline_scope(self):
        now = time.time()
        base = {
            "checkout_protocol_hint": "oaics",
            "checkout_protocol_hint_country": "DE",
            "checkout_protocol_hint_currency": "EUR",
            "checkout_protocol_hint_checked_at": now,
            "checkout_country": "BR",
            "checkout_currency": "BRL",
        }
        self.assertFalse(app.checkout_protocol_hint_matches(base, now=now))
        self.assertTrue(app.checkout_protocol_hint_matches({
            **base,
            "checkout_protocol_hint_baseline": True,
        }, now=now))
        self.assertFalse(app.checkout_protocol_hint_matches({
            **base,
            "checkout_protocol_hint_baseline": True,
            "checkout_protocol_hint_checked_at": now - app.CHECKOUT_PROTOCOL_HINT_TTL_SECONDS - 1,
        }, now=now))

    def test_oaics_hint_forces_initial_checkout_billing_to_de_eur(self):
        country, currency, source = app.resolve_oaics_checkout_region(
            "BR",
            "BRL",
            "当前国家支持 PayPal（国家币种映射）",
            oaics_hint_active=True,
        )

        self.assertEqual((country, currency), ("DE", "EUR"))
        self.assertIn("OAICS", source)

    def test_unmarked_checkout_keeps_proxy_derived_region(self):
        result = app.resolve_oaics_checkout_region(
            "BR",
            "BRL",
            "当前国家支持 PayPal（国家币种映射）",
            oaics_hint_active=False,
        )

        self.assertEqual(
            result,
            ("BR", "BRL", "当前国家支持 PayPal（国家币种映射）"),
        )

    def test_detection_result_is_not_written_as_a_success_link(self):
        class FakeStore:
            _run_locked = app.JobStore._run_locked

            def __init__(self):
                self.state = {}
                self.successes = 0
                self.finalized = 0

            def cancelled(self, _job_id):
                return False

            def get(self, _job_id):
                return dict(self.state)

            def log(self, _job_id, _message):
                return None

            def update(self, _job_id, **fields):
                self.state.update(fields)

            def _record_success(self, _job_id, _result):
                self.successes += 1

            def _finalize_oaics_fallback(self, _job_id, _result):
                self.finalized += 1

            def _run_single(self, _job_id, _options):
                self.state.update({
                    "status": "done",
                    "result": {
                        "detection_only": True,
                        "checkout_protocol": "oaics",
                    },
                })

        store = FakeStore()
        store._run_locked("job-detect", {
            "retry_count": 1,
            "link_type": "paypal",
            "country": "DE",
            "currency": "EUR",
            "entry_proxies": ["proxy-a"],
            "exit_proxies": ["proxy-b"],
            "detection_only": True,
            "detection_fixed_de": True,
        })
        self.assertEqual(store.successes, 0)
        self.assertEqual(store.finalized, 0)

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

    def test_checkout_payment_methods_detect_paypal_from_types_and_specs(self):
        payload = {
            "checkout_session_id": "oaics_test_internal",
            "payment_method_types": ["card", "paypal"],
            "payment_method_specs": [{"type": "paypal"}],
        }

        self.assertEqual(
            app.extract_checkout_payment_methods(payload),
            ["card", "paypal"],
        )
        self.assertTrue(app.checkout_supports_paypal(payload))

    def test_checkout_payment_methods_detect_paypal_custom_variant(self):
        payload = {
            "checkout_session": {
                "custom_payment_methods": [
                    {"provider": "PayPal Express"},
                ],
            },
            "note": "paypal should not be read from arbitrary fields",
        }

        self.assertEqual(
            app.extract_checkout_payment_methods(payload),
            ["paypal"],
        )

    def test_checkout_payment_methods_do_not_read_arbitrary_text(self):
        payload = {
            "description": "paypal",
            "metadata": {"provider": "paypal"},
        }

        self.assertEqual(app.extract_checkout_payment_methods(payload), [])
        self.assertFalse(app.checkout_supports_paypal(payload))

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

    def test_promo_not_applied_stops_retry_wrapper(self):
        class FakeStore:
            _run_locked = app.JobStore._run_locked

            def __init__(self):
                self.attempts = 0
                self.state = {}
                self.updates = []

            def cancelled(self, _job_id):
                return False

            def get(self, _job_id):
                return dict(self.state)

            def log(self, _job_id, _message):
                return None

            def _record_success(self, _job_id, _result):
                return None

            def update(self, _job_id, **fields):
                self.updates.append(fields)
                self.state.update(fields)

            def _run_single(self, _job_id, _options):
                self.attempts += 1
                self.state.update({
                    "status": "error",
                    "error": "Plus 首月免费优惠未生效：Stripe 今日应付 amount=2000",
                    "error_code": app.PROMO_NOT_APPLIED_ERROR_CODE,
                })

        store = FakeStore()
        store._run_locked("job-promo", {
            "retry_count": 5,
            "link_type": "hosted",
            "country": "US",
            "entry_proxies": ["proxy-a"],
            "exit_proxies": ["proxy-a"],
        })
        self.assertEqual(store.attempts, 1)
        self.assertEqual(store.state["status"], "error")
        self.assertEqual(store.state["error_code"], app.PROMO_NOT_APPLIED_ERROR_CODE)

    def test_account_block_streak_stops_after_three_attempts(self):
        class FakeStore:
            _run_locked = app.JobStore._run_locked

            def __init__(self):
                self.attempts = 0
                self.state = {}

            def cancelled(self, _job_id):
                return False

            def get(self, _job_id):
                return dict(self.state)

            def log(self, _job_id, _message):
                return None

            def update(self, _job_id, **fields):
                self.state.update(fields)

            def _run_single(self, _job_id, _options):
                self.attempts += 1
                self.state.update({
                    "status": "error",
                    "error": "account blocked by policy",
                    "error_code": "account_blocked",
                })

        store = FakeStore()
        store._run_locked("job-block", {
            "retry_count": 10,
            "link_type": "hosted",
            "country": "US",
            "entry_proxies": ["proxy-a"],
            "exit_proxies": ["proxy-a"],
        })
        self.assertEqual(store.attempts, app.ACCOUNT_BLOCK_STREAK_LIMIT)
        self.assertEqual(store.state["error_code"], app.ACCOUNT_BLOCK_FUSE_ERROR_CODE)

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

    def test_oaics_conversion_failed_error_is_retryable(self):
        """测试 OaicsConversionFailedError 异常的 error_code"""
        error = app.OaicsConversionFailedError("转换失败需要重试")
        self.assertEqual(
            error.error_code,
            app.OAICS_CONVERSION_FAILED_ERROR_CODE,
        )

    def test_oaics_retry_count_in_options(self):
        """测试 options 中的 _oaics_retry_count 字段正确递增"""
        class FakeStore:
            _run_locked = app.JobStore._run_locked

            def __init__(self):
                self.attempts = 0
                self.seen_retry_counts = []
                self.state = {}

            def cancelled(self, _job_id):
                return False

            def get(self, _job_id):
                return dict(self.state)

            def log(self, _job_id, _message):
                return None

            def update(self, _job_id, **fields):
                self.state.update(fields)

            def _record_success(self, _job_id, _result):
                return None

            def _finalize_oaics_fallback(self, _job_id, _result):
                return None

            def _run_single(self, _job_id, options):
                self.attempts += 1
                self.seen_retry_counts.append(options.get("_oaics_retry_count", 0))
                if options.get("_oaics_retry_count", 0) < app.MAX_OAICS_RETRY:
                    self.state.update({
                        "status": "error",
                        "error": "oaics conversion failed",
                        "error_code": app.OAICS_CONVERSION_FAILED_ERROR_CODE,
                    })
                else:
                    self.state.update({
                        "status": "done",
                        "result": {
                            "checkout_session_id": "cs_live_after_oaics_retry",
                            "checkout_flow": "stripe",
                        },
                    })

        store = FakeStore()
        store._run_locked("job-oaics-retry", {
            "retry_count": 1,
            "link_type": "paypal",
            "country": "US",
            "entry_proxies": ["proxy-a", "proxy-b"],
            "exit_proxies": ["proxy-c", "proxy-d"],
        })
        self.assertEqual(store.attempts, app.MAX_OAICS_RETRY + 1)
        self.assertEqual(store.seen_retry_counts, list(range(app.MAX_OAICS_RETRY + 1)))
        self.assertEqual(store.state["status"], "done")

    def test_max_oaics_retry_constant(self):
        """测试 MAX_OAICS_RETRY 常量存在且为合理值"""
        self.assertTrue(hasattr(app, "MAX_OAICS_RETRY"))
        self.assertIsInstance(app.MAX_OAICS_RETRY, int)
        self.assertGreaterEqual(app.MAX_OAICS_RETRY, 1)
        self.assertLessEqual(app.MAX_OAICS_RETRY, 5)


if __name__ == "__main__":
    unittest.main()
