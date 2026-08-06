import unittest
from unittest.mock import patch

import app


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class FakeHttp:
    def __init__(self, response):
        self.responses = list(response) if isinstance(response, (list, tuple)) else [response]
        self.calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]

    def close(self):
        self.closed = True


class ProxyProbeTests(unittest.TestCase):
    def test_light_probe_uses_one_request_and_returns_ip_country(self):
        http = FakeHttp(FakeResponse({
            "ip": "203.0.113.7",
            "country_code": "GB",
            "country_name": "United Kingdom",
        }))
        with patch.object(app.sc, "build_http", return_value=http):
            result = app.probe_proxy_identity("http://proxy.example:8080")

        self.assertEqual(result["ip"], "203.0.113.7")
        self.assertEqual(result["country"], "GB")
        self.assertEqual(result["country_name"], "United Kingdom")
        self.assertEqual(len(http.calls), 1)
        self.assertEqual(http.calls[0][0], app.PROXY_PROBE_URL)
        self.assertTrue(app.PROXY_PROBE_URL.startswith("https://"))
        self.assertTrue(http.closed)

    def test_probe_endpoint_randomly_selects_one_proxy_without_returning_credentials(self):
        selected = "http://user:secret@gb.example:8080"
        with patch.object(app.secrets, "choice", return_value=selected), patch.object(
            app, "probe_proxy_identity", return_value={
                "ip": "203.0.113.7",
                "country": "GB",
                "country_name": "United Kingdom",
            },
        ) as probe:
            response = app.app.test_client().post(
                "/api/proxy-probe",
                json={
                    "pool": "代理池 2",
                    "proxies": [selected, "http://other.example:8080"],
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["selected_index"], 1)
        self.assertEqual(body["pool_size"], 2)
        self.assertEqual(body["ip"], "203.0.113.7")
        self.assertEqual(body["country"], "GB")
        self.assertNotIn("secret", response.get_data(as_text=True))
        probe.assert_called_once_with(selected)

    def test_probe_falls_back_after_upstream_404(self):
        http = FakeHttp([
            FakeResponse({}, status_code=404),
            FakeResponse({"ip": "203.0.113.8", "country": "GB"}),
        ])
        with patch.object(app.sc, "build_http", return_value=http):
            result = app.probe_proxy_identity("http://proxy.example:8080")

        self.assertEqual(result["ip"], "203.0.113.8")
        self.assertEqual(result["country"], "GB")
        self.assertEqual(len(http.calls), 2)
        self.assertEqual(http.calls[0][0], app.PROXY_PROBE_URLS[0])
        self.assertEqual(http.calls[1][0], app.PROXY_PROBE_URLS[1])


if __name__ == "__main__":
    unittest.main()
