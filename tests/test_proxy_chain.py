import os
import unittest
from unittest.mock import patch

from curl_cffi.const import CurlOpt

import stripe_checkout as sc


class ProxyChainTests(unittest.TestCase):
    def test_pool_proxy_uses_local_pre_proxy_by_default(self):
        with patch.dict(
            os.environ,
            {sc.PROXY_PRE_PROXY_ENV: "http://127.0.0.1:9697"},
            clear=False,
        ):
            http = sc.build_http("http://pool.example:8080")
            try:
                self.assertEqual(
                    http.proxies,
                    {
                        "http": "http://pool.example:8080",
                        "https": "http://pool.example:8080",
                    },
                )
                self.assertEqual(
                    http.curl_options.get(CurlOpt.PRE_PROXY),
                    "http://127.0.0.1:9697",
                )
            finally:
                http.close()

    def test_empty_pre_proxy_restores_direct_pool_connection(self):
        with patch.dict(os.environ, {sc.PROXY_PRE_PROXY_ENV: ""}, clear=False):
            http = sc.build_http("http://pool.example:8080")
            try:
                self.assertNotIn(CurlOpt.PRE_PROXY, http.curl_options)
                self.assertEqual(
                    http.proxies["https"],
                    "http://pool.example:8080",
                )
            finally:
                http.close()

    def test_pre_proxy_accepts_host_port_configuration(self):
        with patch.dict(os.environ, {sc.PROXY_PRE_PROXY_ENV: "127.0.0.1:9697"}, clear=False):
            self.assertEqual(sc.proxy_pre_proxy(), "http://127.0.0.1:9697")


if __name__ == "__main__":
    unittest.main()
