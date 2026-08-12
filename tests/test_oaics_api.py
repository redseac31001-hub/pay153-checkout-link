import os
import unittest
from unittest.mock import patch

from oaics_api import (
    build_confirmation_token_data,
    create_confirmation_token,
    create_oaics_elements_session,
    extract_paypal_ba_url,
    run_oaics_paypal_api_confirmation,
)


class _Response:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = str(payload)

    def json(self):
        return self._payload


class _Http:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class OaicsApiTests(unittest.TestCase):
    def test_elements_session_uses_one_stripe_version_transport(self):
        http = _Http([
            _Response({
                "id": "elements_session_test",
                "config_id": "config_test",
            })
        ])

        create_oaics_elements_session(
            http,
            checkout_data={
                "publishable_key": "pk_live_test",
                "customer_session_client_secret": "cuss_secret_test",
                "payment_method_types": ["paypal", "card"],
            },
            country="DE",
            currency="eur",
            payment_methods=["paypal", "card"],
        )

        request = http.calls[0][1]
        self.assertIn("_stripe_version", request["params"])
        self.assertNotIn("Stripe-Version", request["headers"])

    def test_confirmation_tokens_uses_one_stripe_version_transport(self):
        http = _Http([_Response({"id": "ctoken_test"})])

        result = create_confirmation_token(
            http,
            publishable_key="pk_live_test",
            session_id="oaics_test",
            billing={"name": "Juniper", "address": {"country": "DE"}},
            currency="eur",
            payment_methods=["paypal", "card"],
            checkout_data={
                "elements_session_id": "elements_session_test",
                "elements_session_config_id": "config_test",
            },
            log=lambda _message: None,
        )

        request = http.calls[0][1]
        self.assertEqual(result["confirmation_token"], "ctoken_test")
        self.assertIn("_stripe_version", request["data"])
        self.assertNotIn("Stripe-Version", request["headers"])

    def test_confirmation_token_data_matches_har_protocol_shape(self):
        with patch.dict(os.environ, {"PAY153_OAICS_HCAPTCHA_TOKEN": ""}, clear=False):
            data = build_confirmation_token_data(
                publishable_key="pk_live_test",
                session_id="oaics_test",
                billing={
                    "name": "Juniper",
                    "email": "juniper@example.test",
                    "address": {
                        "line1": "576 River Street",
                        "city": "London",
                        "country": "GB",
                        "postal_code": "GU35 8QS",
                        "state": "",
                    },
                },
                currency="GBP",
                payment_methods=["card", "link", "paypal"],
            )

        self.assertEqual(data["payment_method_data[type]"], "paypal")
        self.assertEqual(data["payment_method_data[billing_details][address][country]"], "GB")
        self.assertEqual(data["client_context[payment_method_types][0]"], "paypal")
        self.assertEqual(data["client_context[payment_method_types][1]"], "card")
        self.assertEqual(data["client_context[payment_method_types][2]"], "link")
        self.assertIn("stripe.js/", data["payment_method_data[payment_user_agent]"])
        self.assertNotIn("payment_method_data[radar_options][hcaptcha_token]", data)

    def test_blocked_confirm_is_returned_without_inventing_ba_link(self):
        http = _Http([
            _Response({"id": "ctoken_test"}),
            _Response({"status": "blocked"}),
        ])
        result = run_oaics_paypal_api_confirmation(
            http=http,
            checkout_data={"publishable_key": "pk_live_test"},
            checkout_url="https://chatgpt.com/checkout/openai_llc/oaics_test",
            session_id="oaics_test",
            billing={"name": "Juniper", "address": {"country": "GB"}},
            currency="gbp",
            payment_methods=["paypal", "card", "link"],
            device_id="device-test",
            language="en-GB",
            sentinel_headers={"OpenAI-Sentinel-Token": "{}"},
            access_token="access-test",
        )

        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["ba_url"])
        self.assertTrue(result["confirmation_token_present"])
        self.assertEqual(len(http.calls), 2)
        self.assertIn("/v1/confirmation_tokens", http.calls[0][0])
        self.assertIn("/checkout/confirm", http.calls[1][0])
        self.assertEqual(
            http.calls[1][1]["json"],
            {
                "checkout_session_id": "oaics_test",
                "confirm_token": "ctoken_test",
                "selected_payment_method_type": "paypal",
            },
        )

    def test_confirm_response_ba_link_is_extracted(self):
        ba_url = "https://www.paypal.com/agreements/approve?ba_token=BA-test_123"
        http = _Http([
            _Response({"id": "ctoken_test"}),
            _Response({"status": "approved", "redirect_url": ba_url}),
        ])
        result = run_oaics_paypal_api_confirmation(
            http=http,
            checkout_data={"publishable_key": "pk_live_test"},
            checkout_url="https://chatgpt.com/checkout/openai_llc/oaics_test",
            session_id="oaics_test",
            billing={"name": "Juniper", "address": {"country": "GB"}},
            currency="gbp",
            payment_methods=["paypal"],
            device_id="device-test",
            language="en-GB",
            sentinel_headers={"OpenAI-Sentinel-Token": "{}"},
        )

        self.assertEqual(result["status"], "ba_found")
        self.assertEqual(result["ba_url"], ba_url)
        self.assertEqual(extract_paypal_ba_url({"url": ba_url}), ba_url)

    def test_standard_oaics_flow_confirms_setup_intent_and_resolves_redirect(self):
        ba_url = "https://www.paypal.com/agreements/approve?ba_token=BA-standard_123"
        http = _Http(
            [
                _Response(
                    {
                        "publishable_key": "pk_live_test",
                        "customer_session_client_secret": "cuss_secret_test",
                        "payment_method_types": ["card", "link", "paypal"],
                        "amount_total": 0,
                    }
                ),
                _Response({"amount_total": 0, "currency": "eur"}),
                _Response(
                    {
                        "id": "elements_session_test",
                        "config_id": "config_test",
                        "customer": "cus_test",
                    }
                ),
                _Response({"id": "ctoken_test"}),
                _Response(
                    {
                        "status": "success",
                        "type": "setup_intent",
                        "client_secret": "seti_test_secret_value",
                        "confirm_return_url": "https://chatgpt.com/checkout/return",
                    }
                ),
                _Response(
                    {
                        "next_action": {
                            "redirect_to_url": {
                                "url": "https://pm-redirects.stripe.com/authorize/test"
                            }
                        }
                    }
                ),
                _Response({}, status_code=302, headers={"Location": ba_url}),
            ]
        )

        result = run_oaics_paypal_api_confirmation(
            http=http,
            checkout_data={
                "publishable_key": "pk_live_test",
                "processor_entity": "openai_ie",
                "customer_session_client_secret": "cuss_secret_test",
            },
            checkout_url="https://chatgpt.com/checkout/openai_ie/oaics_test",
            session_id="oaics_test",
            billing={
                "name": "Juniper",
                "email": "juniper@example.test",
                "address": {"country": "DE", "city": "Berlin"},
            },
            currency="eur",
            payment_methods=["card", "link", "paypal"],
            device_id="device-test",
            language="de-DE",
            sentinel_headers={"OpenAI-Sentinel-Token": "{}"},
            access_token="access-test",
            processor_entity="openai_ie",
            country="DE",
            oai_session_id="session-test",
            require_zero=True,
        )

        self.assertEqual(result["status"], "ba_found")
        self.assertEqual(result["ba_url"], ba_url)
        self.assertTrue(result["intent_confirmed"])
        self.assertEqual(len(http.calls), 7)
        self.assertIn("/v1/elements/sessions", http.calls[2][0])
        self.assertIn("/v1/setup_intents/seti_test/confirm", http.calls[5][0])
        self.assertIn("Authorization", http.calls[4][1]["headers"])
        self.assertIn("oai-session-id", http.calls[4][1]["headers"])
        self.assertEqual(http.calls[1][1]["json"]["billing_country"], "DE")


if __name__ == "__main__":
    unittest.main()
