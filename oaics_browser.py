"""OAICS 原生 PayPal 确认流程。

OAICS Checkout 不暴露 Stripe ``cs_*`` payment-page ID 时，不能把内部的
``oaics_*`` 直接交给 ``/v1/payment_pages``。官方页面本身会先让 Stripe.js
创建 ``confirmation_token``，再调用 ChatGPT 的
``/backend-api/payments/checkout/confirm``。本模块只负责驱动这个官方页面、
观察网络结果并提取已经生成的 PayPal agreements/approve 链接。

浏览器仍然必须经过 PAY153 的双跳代理：
``Chromium -> 本地 HTTP 中继 -> 9697 SOCKS5 -> 代理池出口``。
Chromium 没有 curl 的 CURLOPT_PRE_PROXY，因此这里提供一个仅绑定回环地址的
轻量 HTTP CONNECT 中继，避免浏览器路径绕过 9697。
"""

from __future__ import annotations

import base64
import json
import os
import re
import select
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit


BA_URL_RE = re.compile(
    r"https://(?:www\.)?paypal\.com/agreements/approve\?[^\s\"'<>]+",
    re.IGNORECASE,
)
BA_TOKEN_RE = re.compile(r"(?:^|[?&])ba_token=(BA-[A-Za-z0-9_-]+)", re.IGNORECASE)


class OaicsBrowserError(RuntimeError):
    """OAICS 浏览器确认流程失败。"""


class OaicsBrowserUnavailableError(OaicsBrowserError):
    """运行环境没有可用的 Playwright/Chromium。"""


@dataclass(frozen=True)
class _ProxySpec:
    scheme: str
    host: str
    port: int
    username: str = ""
    password: str = ""


def _proxy_spec(raw: str | None, default_scheme: str = "http") -> _ProxySpec | None:
    value = str(raw or "").strip()
    if not value:
        return None
    if "://" not in value:
        value = f"{default_scheme}://{value}"
    parsed = urlsplit(value)
    host = parsed.hostname
    if not host:
        raise OaicsBrowserError("代理地址缺少主机")
    try:
        port = parsed.port
    except ValueError as exc:
        raise OaicsBrowserError("代理端口格式不正确") from exc
    if port is None:
        port = 443 if parsed.scheme.lower() == "https" else 80
    if not 1 <= int(port) <= 65535:
        raise OaicsBrowserError("代理端口超出范围")
    return _ProxySpec(
        parsed.scheme.lower(),
        host,
        int(port),
        unquote(parsed.username or ""),
        unquote(parsed.password or ""),
    )


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(min(65536, remaining))
        if not chunk:
            raise OaicsBrowserError("代理连接提前关闭")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_until(sock: socket.socket, marker: bytes, limit: int = 131072) -> bytes:
    data = bytearray()
    while marker not in data:
        chunk = sock.recv(8192)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > limit:
            raise OaicsBrowserError("代理请求头过大")
    if marker not in data:
        raise OaicsBrowserError("代理请求头不完整")
    return bytes(data)


def _socks5_connect(
    sock: socket.socket,
    host: str,
    port: int,
    username: str = "",
    password: str = "",
) -> None:
    methods = b"\x00"
    if username or password:
        methods = b"\x00\x02"
    sock.sendall(b"\x05" + bytes([len(methods)]) + methods)
    greeting = _recv_exact(sock, 2)
    if greeting[0] != 5:
        raise OaicsBrowserError("SOCKS5 前置代理版本不匹配")
    method = greeting[1]
    if method == 2:
        if not username and not password:
            raise OaicsBrowserError("SOCKS5 前置代理要求认证")
        user = username.encode("utf-8")[:255]
        secret = password.encode("utf-8")[:255]
        sock.sendall(b"\x01" + bytes([len(user)]) + user + bytes([len(secret)]) + secret)
        auth = _recv_exact(sock, 2)
        if auth[1] != 0:
            raise OaicsBrowserError("SOCKS5 前置代理认证失败")
    elif method != 0:
        raise OaicsBrowserError(f"SOCKS5 前置代理不支持认证方式 {method}")

    try:
        socket.inet_pton(socket.AF_INET, host)
        address = b"\x01" + socket.inet_aton(host)
    except OSError:
        try:
            address = b"\x04" + socket.inet_pton(socket.AF_INET6, host)
        except OSError:
            encoded = host.encode("idna")[:255]
            address = b"\x03" + bytes([len(encoded)]) + encoded
    sock.sendall(b"\x05\x01\x00" + address + int(port).to_bytes(2, "big"))
    reply = _recv_exact(sock, 4)
    if reply[0] != 5 or reply[1] != 0:
        raise OaicsBrowserError(f"SOCKS5 连接目标失败：code={reply[1]}")
    atyp = reply[3]
    if atyp == 1:
        _recv_exact(sock, 4)
    elif atyp == 3:
        length = _recv_exact(sock, 1)[0]
        _recv_exact(sock, length)
    elif atyp == 4:
        _recv_exact(sock, 16)
    else:
        raise OaicsBrowserError("SOCKS5 返回未知地址类型")
    _recv_exact(sock, 2)


def _connect_via_pre_proxy(
    pre_proxy: _ProxySpec | None,
    host: str,
    port: int,
    timeout: float,
) -> socket.socket:
    if pre_proxy is None:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.settimeout(timeout)
        return sock
    if pre_proxy.scheme not in {"socks5", "socks5h"}:
        raise OaicsBrowserError("浏览器代理中继只支持 socks5 前置代理")
    sock = socket.create_connection((pre_proxy.host, pre_proxy.port), timeout=timeout)
    sock.settimeout(timeout)
    _socks5_connect(sock, host, port, pre_proxy.username, pre_proxy.password)
    return sock


def _proxy_authorization(proxy: _ProxySpec | None) -> str:
    if not proxy or not proxy.username:
        return ""
    raw = f"{proxy.username}:{proxy.password}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _target_from_connect(value: str) -> tuple[str, int]:
    target = value.strip()
    if target.startswith("["):
        end = target.find("]")
        if end < 0:
            raise OaicsBrowserError("CONNECT IPv6 地址格式不正确")
        host = target[1:end]
        port = int(target[end + 2 :]) if target[end + 1 :].startswith(":") else 443
        return host, port
    if ":" in target:
        host, port_text = target.rsplit(":", 1)
        return host, int(port_text)
    return target, 443


def _connect_through_pool(
    pool_proxy: _ProxySpec | None,
    pre_proxy: _ProxySpec | None,
    target_host: str,
    target_port: int,
    timeout: float,
) -> socket.socket:
    if pool_proxy is None:
        return _connect_via_pre_proxy(pre_proxy, target_host, target_port, timeout)

    upstream = _connect_via_pre_proxy(pre_proxy, pool_proxy.host, pool_proxy.port, timeout)
    if pool_proxy.scheme in {"socks5", "socks5h"}:
        _socks5_connect(upstream, target_host, target_port, pool_proxy.username, pool_proxy.password)
        return upstream

    if pool_proxy.scheme == "https":
        context = ssl.create_default_context()
        upstream = context.wrap_socket(upstream, server_hostname=pool_proxy.host)

    auth = _proxy_authorization(pool_proxy)
    lines = [
        f"CONNECT {target_host}:{target_port} HTTP/1.1",
        f"Host: {target_host}:{target_port}",
        "Connection: keep-alive",
    ]
    if auth:
        lines.append(f"Proxy-Authorization: {auth}")
    upstream.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
    response = _read_until(upstream, b"\r\n\r\n")
    first_line = response.split(b"\r\n", 1)[0].decode("latin-1", "replace")
    match = re.search(r"\s(\d{3})(?:\s|$)", first_line)
    if not match or int(match.group(1)) < 200 or int(match.group(1)) >= 300:
        raise OaicsBrowserError(f"上游代理 CONNECT 失败：{first_line[:120]}")
    return upstream


def _relay_sockets(left: socket.socket, right: socket.socket) -> None:
    left.settimeout(None)
    right.settimeout(None)
    sockets = [left, right]
    try:
        while True:
            readable, _, _ = select.select(sockets, [], [], 30)
            if not readable:
                continue
            for source in readable:
                data = source.recv(65536)
                if not data:
                    return
                destination = right if source is left else left
                destination.sendall(data)
    except (OSError, ValueError):
        return


class ChainedHttpProxy:
    """只绑定 127.0.0.1 的 HTTP 代理中继。"""

    def __init__(
        self,
        pool_proxy: str | None,
        pre_proxy: str | None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.pool = _proxy_spec(pool_proxy)
        self.pre = _proxy_spec(pre_proxy, "socks5")
        self.log = log or (lambda _message: None)
        self._stop = threading.Event()
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self.address = ""

    def start(self) -> str:
        if self._server is not None:
            return self.address
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(64)
        server.settimeout(0.5)
        self._server = server
        port = int(server.getsockname()[1])
        self.address = f"http://127.0.0.1:{port}"
        self._thread = threading.Thread(target=self._accept_loop, name="oaics-proxy", daemon=True)
        self._thread.start()
        return self.address

    def stop(self) -> None:
        self._stop.set()
        server = self._server
        self._server = None
        if server is not None:
            try:
                server.close()
            except OSError:
                pass
        thread = self._thread
        self._thread = None
        if thread and thread.is_alive():
            thread.join(timeout=2)

    def _accept_loop(self) -> None:
        server = self._server
        if server is None:
            return
        while not self._stop.is_set():
            try:
                client, _address = server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            worker = threading.Thread(target=self._handle_client, args=(client,), daemon=True)
            worker.start()

    def _handle_client(self, client: socket.socket) -> None:
        client.settimeout(30)
        upstream: socket.socket | None = None
        try:
            raw = _read_until(client, b"\r\n\r\n")
            head, _, remainder = raw.partition(b"\r\n\r\n")
            lines = head.decode("latin-1", "replace").split("\r\n")
            parts = lines[0].split() if lines else []
            if len(parts) < 2:
                raise OaicsBrowserError("浏览器代理请求格式不正确")
            method, target = parts[0].upper(), parts[1]
            headers = lines[1:]
            content_length = 0
            for line in headers:
                name, _, value = line.partition(":")
                if name.lower() == "content-length" and _:
                    try:
                        content_length = max(0, int(value.strip()))
                    except ValueError:
                        content_length = 0
            body = remainder
            if len(body) < content_length:
                body += _recv_exact(client, content_length - len(body))

            if method == "CONNECT":
                target_host, target_port = _target_from_connect(target)
                upstream = _connect_through_pool(
                    self.pool, self.pre, target_host, target_port, 30
                )
                client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                _relay_sockets(client, upstream)
                return

            parsed = urlsplit(target)
            if not parsed.hostname:
                raise OaicsBrowserError("HTTP 代理请求缺少目标主机")
            target_host = parsed.hostname
            target_port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if self.pool and self.pool.scheme in {"http", "https"}:
                upstream = _connect_via_pre_proxy(self.pre, self.pool.host, self.pool.port, 30)
                if self.pool.scheme == "https":
                    context = ssl.create_default_context()
                    upstream = context.wrap_socket(upstream, server_hostname=self.pool.host)
                request_target = target
                auth = _proxy_authorization(self.pool)
            else:
                upstream = _connect_through_pool(self.pool, self.pre, target_host, target_port, 30)
                request_target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
                auth = ""
            outgoing = [f"{method} {request_target} {parts[2]}"]
            for line in headers:
                name, _, _value = line.partition(":")
                if not _ or name.lower() in {"proxy-connection", "proxy-authorization", "connection"}:
                    continue
                outgoing.append(line)
            if auth:
                outgoing.append(f"Proxy-Authorization: {auth}")
            outgoing.append("Connection: close")
            upstream.sendall(("\r\n".join(outgoing) + "\r\n\r\n").encode("latin-1") + body)
            _relay_sockets(client, upstream)
        except Exception as exc:  # noqa: BLE001
            try:
                body = f"OAICS proxy relay error: {type(exc).__name__}".encode("ascii", "replace")
                client.sendall(
                    b"HTTP/1.1 502 Bad Gateway\r\n"
                    + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("ascii")
                    + body
                )
            except OSError:
                pass
            self.log(f"[oaics] 浏览器代理中继失败：{type(exc).__name__}")
        finally:
            for sock in (client, upstream):
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "off", "no"}


def _profile(country: str) -> dict[str, str]:
    profiles = {
        "US": ("en-US", "America/Chicago"),
        "JP": ("ja-JP", "Asia/Tokyo"),
        "GB": ("en-GB", "Europe/London"),
        "DE": ("de-DE", "Europe/Berlin"),
        "BR": ("pt-BR", "America/Sao_Paulo"),
        "TH": ("th-TH", "Asia/Bangkok"),
        "AU": ("en-AU", "Australia/Sydney"),
    }
    locale, timezone = profiles.get(str(country or "DE").upper(), ("en-US", "America/Chicago"))
    return {"locale": locale, "timezone": timezone, "language": locale}


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _normalise_candidate(value: str) -> str:
    return (
        str(value or "")
        .replace("\\/", "/")
        .replace("&amp;", "&")
        .replace("\\u0026", "&")
    )


def validate_paypal_ba_url(url: str) -> bool:
    try:
        parsed = urlsplit(_normalise_candidate(url))
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    if host not in {"paypal.com", "www.paypal.com"}:
        return False
    if parsed.path.rstrip("/").lower() != "/agreements/approve":
        return False
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    token = str(query.get("ba_token") or "")
    return bool(re.fullmatch(r"BA-[A-Za-z0-9_-]+", token, re.IGNORECASE))


def extract_paypal_ba_url(value: Any) -> str:
    for candidate in _strings(value):
        text = _normalise_candidate(candidate)
        for match in BA_URL_RE.finditer(text):
            url = text[match.start() : match.end()].rstrip(".,)")
            if validate_paypal_ba_url(url):
                return url
    return ""


def _mask_identifier(value: str) -> str:
    text = str(value or "")
    if len(text) <= 16:
        return text
    return f"{text[:10]}***{text[-4:]}"


def _response_json(response) -> dict[str, Any]:
    try:
        payload = response.json()
        return payload if isinstance(payload, dict) else {}
    except Exception:
        try:
            payload = json.loads(response.text())
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}


def _safe_cookie_list(cookies: dict[str, Any] | None) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for name, value in (cookies or {}).items():
        name = str(name or "").strip()
        if not name:
            continue
        result.append({
            "name": name,
            "value": str(value or ""),
            "domain": ".chatgpt.com",
            "path": "/",
        })
    return result


def _field_value(billing: dict[str, Any], key: str) -> str:
    address = billing.get("address") if isinstance(billing, dict) else {}
    address = address if isinstance(address, dict) else {}
    if key == "email":
        return str(billing.get("email") or "")
    if key == "name":
        return str(billing.get("name") or "")
    if key == "phone":
        return str(billing.get("phone") or "")
    return str(address.get(key) or "")


def _fill_billing(page, billing: dict[str, Any], log: Callable[[str], None]) -> None:
    """尽量填充官方页面已有的地址输入框；找不到时交给页面默认值。"""
    field_selectors = {
        "name": [
            'input[autocomplete="name"]',
            'input[name="name"]',
            'input[placeholder*="name" i]',
        ],
        "email": ['input[type="email"]', 'input[autocomplete="email"]'],
        "phone": ['input[type="tel"]', 'input[autocomplete="tel"]'],
        "line1": [
            'input[autocomplete="address-line1"]',
            'input[name*="address" i]',
            'input[placeholder*="address" i]',
        ],
        "city": ['input[autocomplete="address-level2"]', 'input[name="city"]'],
        "state": ['input[autocomplete="address-level1"]', 'input[name="state"]'],
        "postal_code": [
            'input[autocomplete="postal-code"]',
            'input[name*="postal" i]',
            'input[name*="zip" i]',
        ],
    }
    filled = 0
    for frame in list(page.frames):
        for key, selectors in field_selectors.items():
            value = _field_value(billing, key)
            if not value:
                continue
            field_filled = False
            for selector in selectors:
                try:
                    locator = frame.locator(selector)
                    count = min(locator.count(), 3)
                    for index in range(count):
                        item = locator.nth(index)
                        if not item.is_visible():
                            continue
                        current = str(item.input_value() or "").strip()
                        if not current:
                            item.fill(value, timeout=2500)
                            filled += 1
                            field_filled = True
                        break
                    if filled and key:
                        if field_filled:
                            break
                    if field_filled:
                        break
                except Exception:
                    continue
    if filled:
        log(f"[oaics] 官方页面账单字段已补齐：{filled} 项")


def _click_paypal(page) -> bool:
    selectors = [
        'button:has-text("PayPal")',
        '[role="radio"]:has-text("PayPal")',
        '[role="tab"]:has-text("PayPal")',
        'label:has-text("PayPal")',
        'text=PayPal',
    ]
    for frame in list(page.frames):
        for selector in selectors:
            try:
                locator = frame.locator(selector)
                count = min(locator.count(), 8)
                for index in range(count):
                    item = locator.nth(index)
                    if not item.is_visible():
                        continue
                    text = (item.inner_text(timeout=1000) or "").lower()
                    if "paypal" not in text:
                        continue
                    item.click(timeout=4000)
                    return True
            except Exception:
                continue
    return False


def _click_submit(page) -> bool:
    pattern = re.compile(
        r"^(continue|confirm|subscribe|start|pay|complete|get started|try for free|加入|继续|确认|订阅|开始)",
        re.IGNORECASE,
    )
    candidates: list[tuple[int, Any]] = []
    for frame in list(page.frames):
        try:
            for button_selector in ("button", '[role="button"]'):
                locator = frame.locator(button_selector)
                for index in range(min(locator.count(), 40)):
                    item = locator.nth(index)
                    if not item.is_visible():
                        continue
                    text = (item.inner_text(timeout=700) or "").strip()
                    aria = (item.get_attribute("aria-label") or "").strip()
                    label = text or aria
                    lowered = label.lower()
                    if not label or "paypal" in lowered or "cancel" in lowered or "back" in lowered:
                        continue
                    if pattern.search(label):
                        score = 0 if re.match(r"^(continue|subscribe|confirm|pay|开始|继续|确认|订阅)", label, re.I) else 1
                        candidates.append((score, item))
        except Exception:
            continue
    for _score, item in sorted(candidates, key=lambda value: value[0]):
        try:
            item.click(timeout=5000)
            return True
        except Exception:
            continue
    return False


def run_oaics_paypal_confirmation(
    *,
    checkout_url: str,
    session_id: str,
    payment_methods: list[str] | None,
    billing: dict[str, Any] | None,
    pool_proxy: str,
    pre_proxy: str | None,
    cookies: dict[str, Any] | None,
    device_id: str,
    did: str,
    country: str,
    log: Callable[[str], None] = lambda _message: None,
) -> dict[str, Any]:
    """打开 OAICS 页面并返回 BA 捕获结果，不执行 PayPal 最终批准。"""
    if not str(session_id or "").startswith("oaics_"):
        raise OaicsBrowserError("OAICS 原生确认需要 oaics_* Session")
    if not checkout_url:
        raise OaicsBrowserError("OAICS 官方结账地址为空")
    methods = [str(item).lower() for item in (payment_methods or []) if item]
    if methods and "paypal" not in methods:
        return {
            "status": "paypal_unavailable",
            "error": f"OAICS 当前未声明 PayPal，可用方式：{', '.join(methods)}",
            "confirmation_token_present": False,
            "confirm_status": "",
            "ba_url": "",
        }
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - depends on deployment image
        raise OaicsBrowserUnavailableError(
            "OAICS 原生确认需要 Playwright；请安装 playwright 并执行 playwright install chromium"
        ) from exc

    state: dict[str, Any] = {
        "status": "started",
        "confirmation_token_id": "",
        "confirmation_token_present": False,
        "confirmation_http_status": None,
        "confirm_http_status": None,
        "confirm_status": "",
        "ba_url": "",
        "error": "",
        "started_at": time.time(),
    }

    def capture_url(value: Any) -> None:
        if state.get("ba_url"):
            return
        url = extract_paypal_ba_url(value)
        if url:
            state["ba_url"] = url
            state["status"] = "ba_found"

    def on_response(response) -> None:
        url = str(response.url or "")
        capture_url(url)
        if "api.stripe.com/v1/confirmation_tokens" in url:
            state["confirmation_http_status"] = response.status
            payload = _response_json(response)
            token_id = str(payload.get("id") or "")
            if token_id.startswith("ctoken_"):
                state["confirmation_token_id"] = token_id
                state["confirmation_token_present"] = True
                log(f"[oaics] confirmation_tokens 成功：{_mask_identifier(token_id)}")
        if "/backend-api/payments/checkout/confirm" in url:
            state["confirm_http_status"] = response.status
            payload = _response_json(response)
            confirm_status = str(payload.get("status") or payload.get("result") or "").lower()
            if confirm_status:
                state["confirm_status"] = confirm_status
            if confirm_status == "blocked":
                state["status"] = "blocked"
                state["error"] = "checkout/confirm 返回 blocked"
                log("[oaics] checkout/confirm HTTP 200，但 status=blocked")
            elif response.status >= 400:
                state["status"] = "confirm_http_error"
                state["error"] = f"checkout/confirm HTTP {response.status}"
            else:
                log(
                    f"[oaics] checkout/confirm：HTTP {response.status}，"
                    f"status={confirm_status or '未暴露'}"
                )
            capture_url(payload)
            capture_url((response.headers or {}).get("location"))

    def attach_page(page) -> None:
        page.on("response", on_response)
        page.on("request", lambda request: capture_url(request.url))
        page.on("framenavigated", lambda frame: capture_url(frame.url))

    relay = ChainedHttpProxy(pool_proxy, pre_proxy, log)
    relay_url = relay.start()
    log(f"[oaics] 浏览器确认代理链已启动：{relay_url} → 9697 → 代理池出口")
    browser = None
    context = None
    try:
        profile = _profile(country)
        with sync_playwright() as playwright:
            headless = _bool_env("PAY153_OAICS_HEADLESS", True)
            browser = playwright.chromium.launch(
                headless=headless,
                proxy={"server": relay_url},
                args=["--disable-quic"],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
                ),
                locale=profile["locale"],
                timezone_id=profile["timezone"],
                viewport={"width": 1440, "height": 1000},
                extra_http_headers={
                    "OAI-Device-Id": str(device_id or ""),
                    "OAI-Language": profile["language"],
                },
            )
            cookie_list = _safe_cookie_list(cookies)
            if did and not any(item["name"] == "oai-did" for item in cookie_list):
                cookie_list.append({"name": "oai-did", "value": did, "domain": ".chatgpt.com", "path": "/"})
            if cookie_list:
                context.add_cookies(cookie_list)
            context.on("page", attach_page)
            page = context.new_page()
            attach_page(page)
            page.set_default_timeout(4500)
            page.set_default_navigation_timeout(90000)
            try:
                page.goto(checkout_url, wait_until="domcontentloaded", timeout=90000)
            except PlaywrightTimeoutError:
                log("[oaics] 官方页面首屏加载超时，继续检查支付控件")
            page.wait_for_timeout(2500)
            capture_url(page.url)

            if not _click_paypal(page):
                state["status"] = "paypal_ui_not_found"
                state["error"] = "官方 OAICS 页面未找到可点击的 PayPal 选项"
                return state
            log("[oaics] 官方页面已选择 PayPal，准备提交确认")
            _fill_billing(page, billing or {}, log)
            page.wait_for_timeout(600)
            if not _click_submit(page):
                state["status"] = "submit_ui_not_found"
                state["error"] = "官方 OAICS 页面未找到提交按钮"
                return state
            log("[oaics] 已提交官方 PayPal 确认按钮，等待 BA 跳转")

            timeout_seconds = max(15, min(120, int(os.getenv("PAY153_OAICS_CONFIRM_TIMEOUT", "60") or 60)))
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                if state.get("ba_url"):
                    break
                if state.get("status") == "blocked":
                    break
                page.wait_for_timeout(500)
            if state.get("ba_url"):
                state["status"] = "ba_found"
                log("[oaics] 已捕获 PayPal agreements/approve 链接")
            elif state.get("status") == "blocked":
                pass
            elif state.get("confirm_status"):
                state["status"] = "confirm_without_ba"
                state["error"] = "OAICS confirm 已返回，但未捕获 PayPal BA 链接"
            else:
                state["status"] = "confirm_not_observed"
                state["error"] = "未观察到 OAICS checkout/confirm 响应"
            return state
    except OaicsBrowserError:
        raise
    except Exception as exc:  # noqa: BLE001
        state["status"] = "browser_error"
        state["error"] = f"{type(exc).__name__}: {exc}"
        return state
    finally:
        try:
            if context is not None:
                context.close()
        except Exception:
            pass
        try:
            if browser is not None:
                browser.close()
        except Exception:
            pass
        relay.stop()
