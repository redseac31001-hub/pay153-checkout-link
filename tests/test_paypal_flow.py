import os
import unittest
from unittest.mock import patch

import stripe_checkout as sc


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, *_args, **_kwargs):
        self.calls += 1
        return self.responses.pop(0)


class PaypalFlowTests(unittest.TestCase):
    def test_promo_not_applied_is_a_non_retryable_error(self):
        error = sc.PromoNotAppliedError("Plus 首月免费优惠未生效：Stripe 今日应付 amount=2000")
        self.assertEqual(error.error_code, sc.PROMO_NOT_APPLIED_ERROR_CODE)

    def test_incomplete_paypal_billing_is_rejected_before_network(self):
        with self.assertRaisesRegex(RuntimeError, "城市.*邮编"):
            sc._validate_paypal_billing({
                "name": "Customer",
                "email": "customer@example.com",
                "address": {
                    "country": "DE",
                    "line1": "Friedrichstrasse 100",
                    "city": "",
                    "postal_code": "",
                },
            })

    def test_approve_poll_retries_until_redirect_is_available(self):
        redirect = "https://pm-redirects.stripe.com/authorize/test"
        http = FakeHttp([
            FakeResponse(200, {"submission_attempt": {"state": "requires_approval"}}),
            FakeResponse(200, {"next_action": {"redirect_to_url": {"url": redirect}}}),
        ])
        messages = []
        with patch.object(sc.time, "sleep"):
            result = sc.poll_redirect_after_approve(
                http,
                "pk_test",
                "cs_test",
                messages.append,
                max_attempts=2,
            )
        self.assertEqual(result, redirect)
        self.assertEqual(http.calls, 2)
        self.assertTrue(any("1/2" in message for message in messages))

    def test_non_200_poll_is_reported_and_can_retry(self):
        http = FakeHttp([
            FakeResponse(502, {}),
            FakeResponse(200, {"next_action": {"redirect_to_url": {"url": "https://example.test/ok"}}}),
        ])
        messages = []
        with patch.object(sc.time, "sleep"):
            result = sc.poll_redirect_after_approve(
                http,
                "pk_test",
                "cs_test",
                messages.append,
                max_attempts=2,
            )
        self.assertEqual(result, "https://example.test/ok")
        self.assertTrue(any("HTTP 502" in message for message in messages))

    def test_generic_decline_stops_on_first_poll_and_keeps_specific_reason(self):
        http = FakeHttp([
            FakeResponse(200, {
                "submission_attempt": {
                    "state": "failed",
                    "error": {
                        "payment_error": {
                            "code": "setup_attempt_failed",
                            "decline_code": "generic_decline",
                        },
                    },
                },
                "setup_intent": {
                    "status": "requires_payment_method",
                    "last_setup_error": {
                        "code": "setup_attempt_failed",
                        "decline_code": "generic_decline",
                    },
                },
            }),
        ])
        ctx = {}
        messages = []
        result = sc.poll_redirect_after_approve(
            http,
            "pk_test",
            "cs_test",
            messages.append,
            ctx=ctx,
            max_attempts=20,
        )

        self.assertEqual(result, "")
        self.assertEqual(http.calls, 1)
        self.assertEqual(ctx["paypal_poll_failure"]["decline_code"], "generic_decline")
        self.assertEqual(ctx["paypal_poll_failure"]["attempt"], 1)
        message = sc._paypal_poll_failure_message(ctx)
        self.assertIn("generic_decline", message)
        self.assertIn("第 1 次", message)
        self.assertNotIn("20 次未返回跳转", message)

    def test_approve_poll_attempts_are_bounded(self):
        with patch.dict(os.environ, {"PAYPAL_APPROVE_POLL_ATTEMPTS": "99"}, clear=False):
            self.assertEqual(sc.paypal_approve_poll_attempts(), 12)
        with patch.dict(os.environ, {"PAYPAL_APPROVE_POLL_ATTEMPTS": "0"}, clear=False):
            self.assertEqual(sc.paypal_approve_poll_attempts(), 1)
        with patch.dict(os.environ, {"PAYPAL_APPROVE_POLL_ATTEMPTS": "bad"}, clear=False):
            self.assertEqual(sc.paypal_approve_poll_attempts(), 6)


if __name__ == "__main__":
    unittest.main()
