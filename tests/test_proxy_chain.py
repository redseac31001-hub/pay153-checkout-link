import os
import socket
import socketserver
import threading
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
                    "socks5h://127.0.0.1:9697",
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
            self.assertEqual(sc.proxy_pre_proxy(), "socks5h://127.0.0.1:9697")

    def test_http_pool_request_is_carried_through_socks_pre_proxy_to_pool(self):
        records = []

        class PoolHandler(socketserver.BaseRequestHandler):
            def handle(self):
                data = self.request.recv(4096)
                records.append(data.split(b"\r\n", 1)[0].decode("latin1", "replace"))
                body = b"pool-hop"
                self.request.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\nConnection: close\r\n\r\n" + body
                )

        class SocksHandler(socketserver.BaseRequestHandler):
            def handle(self):
                client = self.request
                greeting = client.recv(2)
                if greeting != b"\x05\x01":
                    return
                client.recv(1)
                client.sendall(b"\x05\x00")
                request = client.recv(4)
                if request[:3] != b"\x05\x01\x00":
                    return
                address_type = request[3]
                if address_type == 1:
                    target = socket.inet_ntoa(client.recv(4))
                elif address_type == 3:
                    length = client.recv(1)[0]
                    target = client.recv(length).decode("ascii")
                elif address_type == 4:
                    target = socket.inet_ntop(socket.AF_INET6, client.recv(16))
                else:
                    return
                port = int.from_bytes(client.recv(2), "big")
                upstream = socket.create_connection((target, port), timeout=5)
                client.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")

                def relay(source, destination):
                    try:
                        while True:
                            chunk = source.recv(65536)
                            if not chunk:
                                break
                            destination.sendall(chunk)
                    except OSError:
                        pass

                thread = threading.Thread(target=relay, args=(client, upstream), daemon=True)
                thread.start()
                relay(upstream, client)
                thread.join(timeout=1)
                upstream.close()

        pool_server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), PoolHandler)
        socks_server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), SocksHandler)
        pool_thread = threading.Thread(target=pool_server.serve_forever, daemon=True)
        socks_thread = threading.Thread(target=socks_server.serve_forever, daemon=True)
        pool_thread.start()
        socks_thread.start()
        try:
            pool_proxy = f"http://127.0.0.1:{pool_server.server_address[1]}"
            pre_proxy = f"http://127.0.0.1:{socks_server.server_address[1]}"
            with patch.dict(os.environ, {sc.PROXY_PRE_PROXY_ENV: pre_proxy}, clear=False):
                http = sc.build_http(pool_proxy)
                try:
                    response = http.get("http://probe.invalid/", timeout=5)
                finally:
                    http.close()
            self.assertEqual(response.text, "pool-hop")
            self.assertEqual(len(records), 1)
            self.assertTrue(records[0].startswith("GET http://probe.invalid/"))
        finally:
            pool_server.shutdown()
            socks_server.shutdown()
            pool_server.server_close()
            socks_server.server_close()


if __name__ == "__main__":
    unittest.main()
