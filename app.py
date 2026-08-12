from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import random
import threading
import time
import uuid
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from cryptography.fernet import Fernet
from flask import Flask, jsonify, request, send_from_directory, session
from curl_cffi import requests

from manage_defaults import DEFAULT_ASN_RECOMMENDATIONS
from manage_store import ManageStore
import stripe_checkout as sc
from provider_checkout import (
    PROVIDER_DEFAULTS,
    default_billing,
    normalize_billing_profile,
    stripe_to_provider,
)
from sentinel_token import SentinelTokenProvider as BaseSentinel

# 加载 .env 文件中的环境变量
ROOT = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")  # 使用绝对路径加载 .env
except ImportError:
    pass  # python-dotenv 未安装，跳过
BACKEND_LOG_DIR = Path(os.getenv("PAY153_LOG_DIR", str(ROOT / "logs")))
LEGACY_SERVICE_BASE = str(os.getenv("PAY153_LEGACY_BASE", "")).rstrip("/")
app = Flask(__name__, static_folder=str(ROOT / "static"), static_url_path="/static")
app.config["JSON_AS_ASCII"] = False
app.config["SECRET_KEY"] = os.getenv("PAY153_SESSION_SECRET", "").strip() or secrets.token_hex(32)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


def _manage_key() -> bytes:
    configured = os.getenv("PAY153_MANAGE_ENCRYPTION_KEY", "").strip()
    if configured:
        try:
            Fernet(configured.encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise RuntimeError("PAY153_MANAGE_ENCRYPTION_KEY 不是有效的 Fernet 密钥") from exc
        return configured.encode("ascii")

    key_path = Path(os.getenv("PAY153_MANAGE_KEY_FILE", str(ROOT / "data" / ".manage.key")))
    key_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        key = key_path.read_bytes().strip()
        Fernet(key)
        return key
    except FileNotFoundError:
        key = Fernet.generate_key()
        key_path.write_bytes(key + b"\n")
        try:
            key_path.chmod(0o600)
        except OSError:
            pass
        return key
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"管理密钥文件无效：{key_path}") from exc


MANAGE_PASSWORD = os.getenv("PAY153_MANAGE_PASSWORD", "").strip()
MANAGE_STORE = ManageStore(
    os.getenv("PAY153_MANAGE_DB", str(ROOT / "data" / "pay153_manage.sqlite3")),
    _manage_key(),
    ROOT / "data" / "success_links.jsonl",
)
MANAGE_STORE.seed_asn_recommendations(DEFAULT_ASN_RECOMMENDATIONS)

STRIPE_CHECKOUT_FRAGMENT = (
    "#fidnandhYHdWcXxpYCc%2FJ2FgY2RwaXEnKSdpamZkaWAnPyd%2FbScpJ3ZwZ3Zmd2x1cWxqa1Brb"
    "HRwYGtgdnZAa2RnaWBhJz9jZGl2YCknYnBkZmRoamlgU2R3bGRrcSc%2FJ2Zqa3F3amknKSdkdWxO"
    "YHwnPyd1blppbHNgWjA0TUp3VnJGM200a31Cakw2aVFEYldvXFN3fzFhUDZjU0pkZ3xGZk5XNnVnQ"
    "E9icEZTRGl0Rn1hfUZQc2pXbTRdUnJXZGZTbGpzUDZuSU5zdW5vbTJMdG5SNTVsXVR2b2o2aycpJ2"
    "N3amhWYHdzYHcnP3F3cGApJ2dkZm5id2pwa2FGamlqdyc%2FJyZjY2NjY2MnKSdpZHxqcHFRfHVgJ"
    "z8ndmxrYmlgWmxxYGgnKSdga2RnaWBVaWRmYG1qaWFgd3YnP3F3cGB4JSUl"
)

_STRIPE_CHECKOUT_SESSION_RE = re.compile(
    r"(?<![A-Za-z0-9_])cs_(?:live|test)_[A-Za-z0-9]+(?![A-Za-z0-9_])"
)
_OPENAI_CHECKOUT_SESSION_RE = re.compile(r"oaics_[A-Za-z0-9_]+")

CHECKOUT_SESSION_CONTRACT_ERROR_CODE = "checkout_session_contract_changed"
OAICS_CONVERSION_FAILED_ERROR_CODE = "oaics_conversion_failed_retry"
PAYPAL_GENERIC_DECLINE_FUSE_ERROR_CODE = "paypal_generic_decline_fuse"
PROMO_NOT_APPLIED_ERROR_CODE = sc.PROMO_NOT_APPLIED_ERROR_CODE
ACCOUNT_BLOCK_FUSE_ERROR_CODE = "account_blocked_fuse"
ACCOUNT_BLOCK_STREAK_LIMIT = max(
    1, int(os.getenv("PAY153_ACCOUNT_BLOCK_STREAK", "3") or 3)
)
MAX_OAICS_RETRY = 0  # OpenAI 已全面切换到 oaics_*，禁用重试以节省时间
# 连续同类 PayPal 风控拒绝达到该次数后结束任务（非官方冷却时长，仅为工程降频）。
# Stripe/PayPal 公开文档未给出 generic_decline 固定等待分钟数。
PAYPAL_GENERIC_DECLINE_STREAK_LIMIT = max(
    1, int(os.getenv("PAYPAL_GENERIC_DECLINE_STREAK", "3") or 3)
)


class CheckoutSessionContractError(RuntimeError):
    """Raised when OpenAI returns a session shape this Stripe adapter cannot use."""

    error_code = CHECKOUT_SESSION_CONTRACT_ERROR_CODE


class OaicsConversionFailedError(RuntimeError):
    """当 oaics_* 无法转换为 cs_live_* 时抛出，触发外层重试逻辑。"""

    error_code = OAICS_CONVERSION_FAILED_ERROR_CODE


class PaypalGenericDeclineFuseError(RuntimeError):
    """连续多次 PayPal generic_decline 后熔断，避免无脑打满重试。"""

    error_code = PAYPAL_GENERIC_DECLINE_FUSE_ERROR_CODE


def is_account_block_error(error: str, error_code: str = "") -> bool:
    """判断是否收到明确的账号封禁/停用信号。"""
    code = str(error_code or "").strip().lower()
    if re.search(r"account_(?:blocked|banned|suspended|restricted)", code):
        return True
    text = str(error or "")
    return bool(re.search(
        r"(?:account|账号|账户).{0,40}(?:blocked|banned|suspend|denied|封禁|停用|冻结|禁止|拒绝)",
        text,
        re.IGNORECASE,
    ))


def is_paypal_risk_decline_error(error: str, error_code: str = "") -> bool:
    """判断是否为 PayPal/Stripe 支付风控类拒绝（可计入连续熔断）。"""
    code = str(error_code or "").strip().lower()
    if code in {PAYPAL_GENERIC_DECLINE_FUSE_ERROR_CODE, "paypal_generic_decline"}:
        return True
    text = str(error or "")
    lowered = text.lower()
    if "generic_decline" in lowered:
        return True
    if "setup_attempt_failed" in lowered:
        return True
    if "checkout_approval_payment_failure" in lowered:
        return True
    # 短路轮询超时在实测中几乎总是 PM 已被拒（见 _poll_last_response.json）
    if ("approve" in lowered or "轮询" in text) and "未返回跳转" in text:
        return True
    if "支付被拒绝" in text or "支付通道拒绝" in text:
        return True
    return False


def is_stripe_checkout_session_id(value: Any) -> bool:
    return bool(_STRIPE_CHECKOUT_SESSION_RE.fullmatch(str(value or "").strip()))


def is_openai_checkout_session_id(value: Any) -> bool:
    return bool(_OPENAI_CHECKOUT_SESSION_RE.fullmatch(str(value or "").strip()))


def openai_managed_checkout_url(
    payload: Any,
    session_id: str,
    processor_entity: str = "",
) -> str:
    """Return the official ChatGPT route for an OpenAI-owned Checkout session."""
    if not is_openai_checkout_session_id(session_id):
        return ""

    candidates: list[str] = []
    if isinstance(payload, dict):
        for key in ("url", "checkout_url"):
            value = str(payload.get(key) or "").strip()
            if value:
                candidates.append(value)
        nested = payload.get("checkout_session")
        if isinstance(nested, dict):
            for key in ("url", "checkout_url"):
                value = str(nested.get(key) or "").strip()
                if value:
                    candidates.append(value)
            processor_entity = str(
                nested.get("processor_entity") or processor_entity or ""
            ).strip()
        processor_entity = str(
            payload.get("processor_entity")
            or payload.get("processor")
            or processor_entity
            or ""
        ).strip()

    for candidate in candidates:
        parsed = urlsplit(candidate)
        if (
            parsed.scheme == "https"
            and parsed.hostname in {"chatgpt.com", "pay.openai.com"}
            and session_id in candidate
        ):
            return candidate

    if not re.fullmatch(r"[A-Za-z_]+", processor_entity):
        return ""
    return (
        "https://chatgpt.com/checkout/"
        f"{quote(processor_entity, safe='_')}/{quote(session_id, safe='_')}"
    )


def extract_stripe_checkout_session_id(payload: Any, raw_text: str = "") -> str:
    """Find the Stripe payment_page ID in an OpenAI Checkout response.

    Recent Checkout responses can expose an ``oaics_*`` OpenAI session ID in
    the top-level ``checkout_session_id`` field while the Stripe
    ``cs_live_*`` ID is nested or only present in a URL.  Stripe's
    ``/v1/payment_pages/<id>/init`` accepts only the latter.
    """

    def visit(value: Any) -> str:
        if isinstance(value, str):
            match = _STRIPE_CHECKOUT_SESSION_RE.search(value)
            return match.group(0) if match else ""
        if isinstance(value, dict):
            preferred_keys = (
                "stripe_checkout_session_id",
                "payment_page_id",
                "checkout_session_id",
                "checkout_url",
                "url",
            )
            for key in preferred_keys:
                if key in value:
                    found = visit(value[key])
                    if found:
                        return found
            for item in value.values():
                found = visit(item)
                if found:
                    return found
        elif isinstance(value, (list, tuple)):
            for item in value:
                found = visit(item)
                if found:
                    return found
        return ""

    return visit(payload) or visit(raw_text)


_CHECKOUT_PAYMENT_METHOD_COLLECTION_KEYS = frozenset({
    "payment_method_types",
    "ordered_payment_method_types",
    "ordered_payment_method_types_and_wallets",
    "payment_method_specs",
    "custom_payment_methods",
})
_CHECKOUT_PAYMENT_METHOD_VALUE_KEYS = frozenset({
    "type",
    "payment_method_type",
    "provider",
    "method",
    "name",
    "code",
})


def _normalize_checkout_payment_method(value: Any) -> str:
    """Normalize a method label without retaining arbitrary response data."""
    if not isinstance(value, str):
        return ""
    token = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    if not token or len(token) > 64:
        return ""
    # OAICS has used several PayPal labels across checkout surfaces.  Keep one
    # canonical value so callers do not need to understand private variants.
    if token == "paypal" or token.startswith("paypal_"):
        return "paypal"
    return token


def extract_checkout_payment_methods(payload: Any) -> list[str]:
    """Extract safe, normalized payment-method labels from Checkout payloads.

    This intentionally reads only known payment-method containers.  It does
    not dump the raw OAICS object, which may contain session credentials or
    customer data.  The result is suitable for capability detection and
    diagnostic logging, not for constructing a private request body.
    """
    methods: list[str] = []

    def add(value: Any) -> None:
        normalized = _normalize_checkout_payment_method(value)
        if normalized and normalized not in methods:
            methods.append(normalized)

    def collect_container(value: Any) -> None:
        if isinstance(value, str):
            add(value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                collect_container(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                lowered = str(key).lower()
                if lowered in _CHECKOUT_PAYMENT_METHOD_VALUE_KEYS:
                    collect_container(item)
                elif lowered == "id" and _normalize_checkout_payment_method(item) == "paypal":
                    add(item)

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in _CHECKOUT_PAYMENT_METHOD_COLLECTION_KEYS:
                    collect_container(item)
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk(payload)
    return methods


def checkout_supports_paypal(payload: Any) -> bool:
    """Return whether a Checkout response advertises a PayPal rail."""
    return "paypal" in extract_checkout_payment_methods(payload)


def _checkout_field_value_kind(key: str, value: Any) -> str:
    """Return a small, non-sensitive description for a checkout response field."""
    if value is None:
        return "null"
    if isinstance(value, dict):
        return "<object>"
    if isinstance(value, (list, tuple)):
        return f"<array:{len(value)}>"
    text = str(value).strip()
    if not text:
        return "<empty>"
    lowered_key = str(key).lower()
    if "url" in lowered_key:
        return "<url>"
    if "secret" in lowered_key or "publishable" in lowered_key or lowered_key in {"key", "token"}:
        return "<redacted>"
    for pattern, label in (
        (r"oaics_[A-Za-z0-9]+", "oaics_*"),
        (r"cs_live_[A-Za-z0-9]+", "cs_live_*"),
        (r"cs_test_[A-Za-z0-9]+", "cs_test_*"),
        (r"pm_[A-Za-z0-9]+", "pm_*"),
        (r"pi_[A-Za-z0-9]+", "pi_*"),
        (r"seti_[A-Za-z0-9]+", "seti_*"),
    ):
        if re.search(pattern, text):
            return label
    if "id" in lowered_key or "session" in lowered_key:
        return f"<string:{len(text)}>"
    return f"<string:{len(text)}>"


def summarize_checkout_response(payload: Any) -> str:
    """Summarize checkout response shape without logging IDs, keys, or URLs.

    The create/update endpoints are private and their response schema can
    change independently of Stripe.  Logging only field names and value kinds
    makes that change diagnosable without persisting payment credentials or
    session material.
    """
    if not isinstance(payload, dict):
        return f"type={type(payload).__name__}"

    root_keys = [str(key) for key in payload.keys()]
    checkout_session_keys: list[str] = []
    interesting: list[str] = []
    seen_paths: set[str] = set()

    def walk(value: Any, path: str = "", depth: int = 0) -> None:
        if depth > 8:
            return
        if isinstance(value, dict):
            if path.rsplit(".", 1)[-1] == "checkout_session":
                checkout_session_keys.extend(str(key) for key in value.keys())
            for key, item in value.items():
                key_text = str(key)
                item_path = f"{path}.{key_text}" if path else key_text
                lowered = key_text.lower()
                if (
                    "id" in lowered
                    or "url" in lowered
                    or "session" in lowered
                    or "payment" in lowered
                    or "secret" in lowered
                    or "publishable" in lowered
                    or lowered in {"processor", "processor_entity", "tag"}
                ) and item_path not in seen_paths:
                    seen_paths.add(item_path)
                    interesting.append(
                        f"{item_path}={_checkout_field_value_kind(key_text, item)}"
                    )
                walk(item, item_path, depth + 1)
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value[:20]):
                walk(item, f"{path}[{index}]", depth + 1)

    walk(payload)
    root = ",".join(root_keys[:40]) or "-"
    nested = ",".join(dict.fromkeys(checkout_session_keys)) or "-"
    fields = "; ".join(interesting[:60]) or "-"
    return f"root_keys=[{root}]; checkout_session_keys=[{nested}]; fields=[{fields}]"


def checkout_session_contract_error(payload: Any, source: str) -> CheckoutSessionContractError:
    """Build the actionable error used when no Stripe payment_page ID exists."""
    source_text = source.strip() or "Checkout"
    return CheckoutSessionContractError(
        f"{source_text} 当前只返回 OpenAI 内部 Session（oaics_*），未返回 "
        "Stripe payment_page 所需的 cs_live_/cs_test_ Session ID；"
        "当前旧 Stripe 初始化链路无法继续。"
        f"响应结构：{summarize_checkout_response(payload)}"
    )

PLANS = {
    "plus": "chatgptplusplan",
    "pro": "chatgptpro",
    "team": "chatgptteamplan",
    "codex_low": "chatgptbusiness_usage_based",
}

OPENAI_CHECKOUT_CURRENCIES = {
    "USD", "AUD", "CAD", "GBP", "EUR", "CLP", "JPY", "INR", "IDR", "PKR",
    "THB", "MYR", "TWD", "VND", "PHP", "NGN", "ZAR", "KZT", "TZS", "EGP",
    "BRL", "SEK", "CZK", "PLN", "DKK", "NOK", "KRW", "COP", "MXN", "PEN",
    "HUF", "QAR", "RON", "ILS", "AED", "SGD", "NZD", "CHF", "SAR",
}

# 国家接口可能返回 OpenAI Checkout 尚未接受的本地币种，例如 BA/BAM。
# 欧洲非欧元国家遇到未开放币种时优先使用 EUR，其余地区回退 USD。
EURO_CURRENCY_FALLBACK_COUNTRIES = {
    "AL", "AD", "AM", "BA", "BG", "BY", "CY", "EE", "GE", "HR", "IS", "LI",
    "LT", "LV", "MC", "MD", "ME", "MK", "MT", "RS", "SM", "SK", "SI", "TR",
    "UA", "VA", "XK",
}


def normalize_checkout_currency(country: str, currency: str = "") -> tuple[str, str]:
    country = str(country or "US").strip().upper()
    detected = str(currency or "").strip().upper()
    if detected in OPENAI_CHECKOUT_CURRENCIES:
        return detected, "代理地区接口"
    mapped = str(sc.currency_for_country(country) or "").upper()
    if country in EURO_CURRENCY_FALLBACK_COUNTRIES and detected not in OPENAI_CHECKOUT_CURRENCIES:
        return "EUR", f"OpenAI币种回退（{detected or mapped or '未知'}→EUR）"
    if mapped in OPENAI_CHECKOUT_CURRENCIES:
        return mapped, "国家币种映射"
    return "USD", f"OpenAI币种回退（{detected or mapped or '未知'}→USD）"


COUNTRY_CURRENCY = {
    country: normalize_checkout_currency(country, currency)[0]
    for country, currency in sc.COUNTRY_CURRENCY.items()
}

_TOKEN_JOB_LOCKS: dict[str, threading.Lock] = {}
_TOKEN_JOB_LOCKS_GUARD = threading.Lock()


def checkout_token_lock(raw_token: str) -> threading.Lock:
    key = hashlib.sha256(str(raw_token or "").strip().encode("utf-8")).hexdigest()
    with _TOKEN_JOB_LOCKS_GUARD:
        return _TOKEN_JOB_LOCKS.setdefault(key, threading.Lock())

PAYPAL_CHECKOUT_REGIONS = {
    country: currency
    for country, currency in sc.COUNTRY_CURRENCY.items()
    if currency in OPENAI_CHECKOUT_CURRENCIES
}


def normalize_paypal_checkout_region(country: str, detected_currency: str = "") -> tuple[str, str, str]:
    # Prefer the proxy country native PayPal Checkout; otherwise use DE/EUR.
    country = str(country or "US").strip().upper()
    detected = str(detected_currency or "").strip().upper()
    direct_countries = {str(item).upper() for item in getattr(sc, "PAYPAL_ORDER_COUNTRIES", [])}
    if country in direct_countries:
        currency, source = normalize_checkout_currency(country, detected)
        return country, currency, f"\u5f53\u524d\u56fd\u5bb6\u652f\u6301 PayPal\uff08{source}\uff09"
    return "DE", "EUR", f"\u5f53\u524d\u56fd\u5bb6 {country} \u672a\u5217\u5165 PayPal \u8d26\u5355\u5730\u533a\uff0c\u56de\u9000 DE/EUR"


def paypal_billing_target_country(
    checkout_country: str,
    payment_country: str = "",
    *,
    force_checkout_country: bool = False,
) -> str:
    """Return the country whose address is used for the PayPal PaymentMethod.

    Direct PayPal regions use the payment-proxy country. Unsupported regions
    share the DE fallback billing used by the OpenAI Checkout.
    """
    checkout_country = str(checkout_country or "DE").strip().upper()
    payment_country = str(payment_country or "").strip().upper()
    direct_countries = {
        str(item).upper() for item in getattr(sc, "PAYPAL_ORDER_COUNTRIES", [])
    }
    if force_checkout_country:
        return checkout_country
    if payment_country and payment_country in direct_countries:
        return payment_country
    return checkout_country


class ProxySentinel(BaseSentinel):
    def __init__(self, proxy: str | None, cookies: dict[str, str]):
        super().__init__(impersonate="chrome136", cookies=cookies)
        self.proxy = proxy

    async def _get_session(self):
        if not self._session:
            kwargs: dict[str, Any] = {
                "impersonate": "chrome",
                "timeout": 70,
                "trust_env": False,
            }
            if self.proxy:
                kwargs["proxies"] = {"http": self.proxy, "https": self.proxy}
                kwargs["curl_options"] = sc.proxy_curl_options(self.proxy)
            self._session = requests.AsyncSession(**kwargs)
        return self._session


def _decode_jwt(token: str) -> dict:
    try:
        part = token.split(".")[1]
        part += "=" * ((4 - len(part) % 4) % 4)
        return json.loads(base64.urlsafe_b64decode(part.encode()).decode())
    except Exception:
        return {}


def extract_access_token(raw: str) -> tuple[str, dict]:
    raw = str(raw or "").strip()
    if not raw:
        raise ValueError("请填写 Access Token 或 Session JSON")
    token = ""
    meta: dict[str, Any] = {}
    if raw.startswith("{"):
        data = json.loads(raw)
        token = str(data.get("accessToken") or data.get("access_token") or "")
        account = data.get("account") or {}
        if isinstance(account, dict):
            meta.update(account)
    if not token:
        match = re.search(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", raw)
        token = match.group(0) if match else raw.splitlines()[0].strip()
    if token.count(".") < 2:
        raise ValueError("Access Token 格式未识别")
    claims = _decode_jwt(token)
    meta.update({
        "email": claims.get("email") or meta.get("email") or "",
        "exp": claims.get("exp"),
        "account_id": (claims.get("https://api.openai.com/auth") or {}).get("chatgpt_account_id")
            or meta.get("id") or "",
    })
    if meta.get("exp") and int(meta["exp"]) <= int(time.time()):
        raise ValueError("Access Token 已过期")
    return token, meta


def normalize_proxy(raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        return ""

    def host_port(text: str) -> tuple[str, int]:
        text = text.strip()
        if text.startswith("[") and "]:" in text:
            host, port_text = text[1:].split("]:", 1)
            host = f"[{host}]"
        else:
            if ":" not in text:
                raise ValueError("代理缺少端口")
            host, port_text = text.rsplit(":", 1)
        if not host or not port_text.isdigit():
            raise ValueError("代理主机或端口格式不正确")
        port = int(port_text)
        if not 1 <= port <= 65535:
            raise ValueError("代理端口超出范围")
        return host, port

    def credentials(text: str) -> tuple[str, str]:
        if ":" not in text:
            raise ValueError("代理凭据格式应为 username:password")
        username, password = text.split(":", 1)
        if not username or not password:
            raise ValueError("代理用户名和密码为空")
        return username, password

    def build(scheme: str, host: str, port: int, username: str = "", password: str = "") -> str:
        auth = ""
        if username or password:
            auth = f"{quote(username, safe='')}:{quote(password, safe='')}@"
        return f"{scheme}://{auth}{host}:{port}"

    if "://" in value:
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https", "socks5", "socks5h"}:
            raise ValueError(f"代理协议 {scheme} 暂未支持")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("代理端口格式不正确") from exc
        if not parsed.hostname or port is None:
            raise ValueError("代理 URL 缺少主机或端口")
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        return build(scheme, host, port, unquote(parsed.username or ""), unquote(parsed.password or ""))

    if value.count("@") == 1:
        left, right = value.split("@", 1)
        try:
            username, password = credentials(left)
            host, port = host_port(right)
            return build("http", host, port, username, password)
        except ValueError:
            host, port = host_port(left)
            username, password = credentials(right)
            return build("http", host, port, username, password)

    parts = value.split(":")
    if len(parts) >= 4 and parts[1].isdigit():
        host, port = host_port(f"{parts[0]}:{parts[1]}")
        return build("http", host, port, parts[2], ":".join(parts[3:]))
    if len(parts) >= 4 and parts[-1].isdigit():
        host, port = host_port(f"{parts[-2]}:{parts[-1]}")
        return build("http", host, port, parts[0], ":".join(parts[1:-2]))

    host, port = host_port(value)
    return build("http", host, port)


def normalize_proxy_pool(raw: Any, label: str) -> list[str]:
    if isinstance(raw, (list, tuple)):
        values = [str(item or "").strip() for item in raw]
    else:
        values = [line.strip() for line in str(raw or "").replace("\r", "").split("\n")]
    values = [value for value in values if value]
    if len(values) > 500:
        raise ValueError(f"{label}最多填写 500 条")
    normalized: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(values, 1):
        try:
            proxy = normalize_proxy(value)
        except ValueError as exc:
            raise ValueError(f"{label}第 {index} 条：{exc}") from exc
        if proxy not in seen:
            normalized.append(proxy)
            seen.add(proxy)
    return normalized


def generate_cpf() -> str:
    digits = [secrets.randbelow(10) for _ in range(9)]
    for weights in (range(10, 1, -1), range(11, 1, -1)):
        value = 11 - sum(number * weight for number, weight in zip(digits, weights)) % 11
        digits.append(0 if value >= 10 else value)
    return "".join(map(str, digits))


def generate_cnpj() -> str:
    digits = [secrets.randbelow(10) for _ in range(12)]
    for weights in ((5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2), (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)):
        value = 11 - sum(number * weight for number, weight in zip(digits, weights)) % 11
        digits.append(0 if value >= 10 else value)
    return "".join(map(str, digits))


def generate_pix_identity(kind: str) -> dict[str, str]:
    first_names = ("Lucas", "Gabriel", "Rafael", "Matheus", "Mariana", "Beatriz", "Camila", "Larissa")
    last_names = ("Silva", "Santos", "Oliveira", "Souza", "Pereira", "Costa", "Rodrigues", "Almeida")
    locations = (
        ("Avenida Paulista 1000", "Sao Paulo", "SP", "01310-100"),
        ("Rua da Assembleia 10", "Rio de Janeiro", "RJ", "20011-901"),
        ("Avenida Afonso Pena 1500", "Belo Horizonte", "MG", "30130-005"),
        ("Rua XV de Novembro 500", "Curitiba", "PR", "80020-310"),
        ("Avenida Sete de Setembro 800", "Salvador", "BA", "40060-001"),
    )
    first, last = secrets.choice(first_names), secrets.choice(last_names)
    line1, city, state, postal_code = secrets.choice(locations)
    if kind == "cnpj":
        name = f"{first.upper()} {last.upper()} COMERCIO E SERVICOS LTDA"
        source = "generated_cnpj"
    else:
        name = f"{first} {last}"
        source = "generated_cpf"
    return {
        "name": name,
        "email": f"{first.lower()}.{last.lower()}{secrets.randbelow(9000) + 1000}@outlook.com",
        "line1": line1,
        "city": city,
        "state": state,
        "postal_code": postal_code,
        "source": source,
    }


def lookup_cnpj_identity(cnpj: str) -> dict[str, str]:
    value = re.sub(r"\D", "", cnpj or "")
    if len(value) != 14:
        return {}
    resp = requests.get(
        f"https://brasilapi.com.br/api/cnpj/v1/{value}",
        headers={"Accept": "application/json", "User-Agent": sc.CHROME_UA},
        timeout=25,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"CNPJ 登记信息查询 HTTP {resp.status_code}")
    data = resp.json() or {}
    street = " ".join(filter(None, [str(data.get("logradouro") or "").strip(), str(data.get("numero") or "").strip()]))
    complement = str(data.get("complemento") or "").strip()
    if complement:
        street = f"{street}, {complement}" if street else complement
    return {
        "name": str(data.get("razao_social") or data.get("nome_fantasia") or "").strip(),
        "line1": street,
        "city": str(data.get("municipio") or "").strip(),
        "state": str(data.get("uf") or "").strip(),
        "postal_code": str(data.get("cep") or "").strip(),
        "status": str(data.get("descricao_situacao_cadastral") or "").strip(),
        "source": "brasilapi_cnpj",
    }


async def sentinel_headers(proxy: str, flow: str, device_id: str, cookie: str) -> dict[str, str]:
    provider = ProxySentinel(proxy or None, {"oai-did": cookie})
    try:
        token, so, diag = await provider.get_token_pair(flow, device_id)
        if not token:
            raise RuntimeError("Sentinel token 生成失败")
        if diag.get("turnstile_required") and not diag.get("has_t"):
            raise RuntimeError("Sentinel 缺少 t")
        if diag.get("so_required") and not diag.get("has_so"):
            raise RuntimeError("Sentinel 缺少 so")
        out = {"OpenAI-Sentinel-Token": json.dumps(token, separators=(",", ":"))}
        if so:
            out["OpenAI-Sentinel-SO-Token"] = json.dumps(so, separators=(",", ":"))
        return out
    finally:
        await provider.close()


def checkout_payload(options: dict, meta: dict) -> dict[str, Any]:
    plan = options["plan"]
    link_type = str(options.get("link_type") or "").strip().lower()
    country = options.get("checkout_country") or options["country"]
    requested_currency = options.get("checkout_currency") or options["currency"]
    currency, _currency_source = normalize_checkout_currency(country, requested_currency)
    options["currency"] = currency
    options["checkout_currency"] = currency
    billing = {"country": country, "currency": currency}
    common: dict[str, Any] = {
        "entry_point": "all_plans_pricing_modal",
        "plan_name": PLANS[plan],
        "billing_details": billing,
        "cancel_url": "https://chatgpt.com/",
        "checkout_ui_mode": "custom" if options["link_type"] != "hosted" or plan == "codex_low" else "redirect",
        "check_card_proxy": True,
    }
    promo = options.get("promo_campaign", "").strip()
    if plan == "team":
        common["entry_point"] = "team_workspace_purchase_modal"
        team_data = {
            "workspace_name": options.get("workspace_name") or "Codex Workspace",
            "price_interval": options.get("price_interval") or "month",
            "seat_quantity": int(options.get("seat_quantity") or 5),
        }
        if options.get("workspace_id"):
            team_data["existing_workspace_id"] = options["workspace_id"]
        common["team_plan_data"] = team_data
        if options.get("promo_code"):
            common["promo_code"] = options["promo_code"]
    elif plan == "codex_low":
        common["entry_point"] = "codex_team_start"
        common["usage_based_workspace_credit_purchase_data"] = {
            "quantity": int(options.get("credit_quantity") or 13),
            "unit": "credit",
            "workspace_name": options.get("workspace_name") or "Codex Space",
            "plan_type": "team",
            "auto_top_up_enabled": True,
        }
    elif plan == "plus" and options.get("use_promo") and (
        link_type not in {"pix", "paypal", "upi", "ideal", "gopay"}
        or (
            options.get("promo_on_create")
            and link_type != "paypal"
        )
    ):
        common["promo_campaign"] = {
            "promo_campaign_id": promo or "plus-1-month-free",
            "is_coupon_from_query_param": False,
        }
    return common


def create_checkout(token: str, payload: dict, proxy: str, device_id: str, did: str, log) -> dict:
    http = sc.build_http(proxy or None)
    try:
        http.cookies.set("oai-did", did, domain="chatgpt.com")
    except Exception:
        pass
    try:
        http.get("https://chatgpt.com/", headers={"User-Agent": sc.CHROME_UA}, timeout=35)
    except Exception as exc:
        log(f"ChatGPT 暖身提示：{type(exc).__name__}")
    s_headers = asyncio.run(sentinel_headers(proxy, "chatgpt_checkout", device_id, did))
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Origin": "https://chatgpt.com",
        "Referer": "https://chatgpt.com/",
        "User-Agent": sc.CHROME_UA,
        "OAI-Language": "zh-CN",
        "OAI-Device-Id": device_id,
        **s_headers,
    }
    resp = http.post(sc.OPENAI_CHECKOUT_URL, json=payload, headers=headers, timeout=60)
    text = resp.text or ""
    if resp.status_code != 200:
        raise RuntimeError(f"OpenAI Checkout HTTP {resp.status_code}: {text[:500]}")
    try:
        data = resp.json()
    except Exception:
        raise RuntimeError(f"OpenAI Checkout 返回非 JSON：{text[:300]}")
    log(f"[checkout] response schema: {summarize_checkout_response(data)}")
    detected_methods = extract_checkout_payment_methods(data)
    if detected_methods:
        log(f"[checkout] 可用支付方式（脱敏）：{detected_methods}")
    raw_session_id = str(data.get("checkout_session_id") or "").strip()
    url = data.get("url") or ""
    sid = extract_stripe_checkout_session_id(data, text)
    if raw_session_id and raw_session_id != sid:
        data["openai_checkout_session_id"] = raw_session_id
        if sid:
            log(
                f"[checkout] 使用 Stripe Session {sid[:32]}，忽略 OpenAI 内部 Session "
                f"{raw_session_id[:32]}"
            )
    # Keep an oaics_* ID available for /checkout/update materialization.  It
    # must never be sent to Stripe's /payment_pages/<id>/init directly.
    if not sid:
        sid = raw_session_id
    data["checkout_session_id"] = sid
    if is_openai_checkout_session_id(sid):
        data["openai_checkout_session_id"] = sid
        data["checkout_url"] = openai_managed_checkout_url(data, sid)
    else:
        data["checkout_url"] = url or (
            f"https://pay.openai.com/c/pay/{sid}{STRIPE_CHECKOUT_FRAGMENT}" if sid else ""
        )
    return {"data": data, "http": http}


def preflight_trial_eligibility(token: str, account_id: str, proxy: str, device_id: str, did: str, log) -> dict:
    if not account_id:
        return {}
    http = sc.build_http(proxy)
    try:
        http.cookies.set("oai-did", did, domain="chatgpt.com")
    except Exception:
        pass
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "*/*",
        "Origin": "https://chatgpt.com",
        "Referer": "https://chatgpt.com/",
        "User-Agent": sc.CHROME_UA,
        "OAI-Language": "zh-CN",
        "OAI-Device-Id": device_id,
    }
    try:
        resp = http.get(
            "https://chatgpt.com/backend-api/payments/payment_methods",
            params={"account_id": account_id},
            headers=headers,
            timeout=35,
        )
        if resp.status_code != 200:
            log(f"优惠预检返回 HTTP {resp.status_code}")
            return {}
        data = resp.json() or {}
        log(
            "入口支付标记 one_click_trial_eligible={}（仅为 payment_methods 字段，不作为活动资格判定）".format(
                data.get("one_click_trial_eligible")
            )
        )
        return data
    except Exception as exc:
        log(f"优惠预检提示：{type(exc).__name__}")
        return {}


def promo_campaign_from_payload(payload: Any) -> str:
    """Extract the account-specific campaign id returned by OpenAI.

    Campaign ids are not guaranteed to stay equal to the UI label.  The update
    endpoint may accept a stale/default id and still return ``success=true``,
    while final approval rejects it as ``invalid_promotion``.
    """
    candidates: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                key_lower = str(key).lower()
                if key_lower in {
                    "promo_campaign_id",
                    "promotion_campaign_id",
                    "campaign_id",
                } and isinstance(item, str):
                    candidate = item.strip()
                    if candidate:
                        candidates.append(candidate)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return candidates[0] if candidates else ""


PROXY_PROBE_URLS = (
    "https://ipinfo.io/json",
    "https://ipapi.co/json/",
)
PROXY_PROBE_URL = PROXY_PROBE_URLS[0]
PROXY_PROBE_TIMEOUT = 12


def probe_proxy_identity(proxy: str) -> dict[str, str]:
    """Make the smallest successful number of requests and report proxy identity."""
    http = sc.build_http(proxy)
    errors: list[str] = []
    try:
        for url in PROXY_PROBE_URLS:
            try:
                resp = http.get(url, timeout=PROXY_PROBE_TIMEOUT)
                if resp.status_code != 200:
                    errors.append(f"{url} HTTP {resp.status_code}")
                    continue
                data = resp.json() or {}
                if str(data.get("status") or "success").lower() == "fail":
                    errors.append(f"{url} upstream rejected probe")
                    continue
                ip = str(data.get("ip") or data.get("query") or "").strip()
                country_value = str(data.get("country_code") or data.get("countryCode") or "").strip()
                if not country_value and re.fullmatch(r"[A-Za-z]{2}", str(data.get("country") or "")):
                    country_value = str(data.get("country") or "")
                country = country_value.upper()
                if not ip or not re.fullmatch(r"[A-Z]{2}", country):
                    errors.append(f"{url} response missing ip/country")
                    continue
                country_name = str(data.get("country_name") or data.get("country") or country).strip()
                if country_name.upper() == country:
                    country_name = country
                return {
                    "ip": ip,
                    "country": country,
                    "country_name": country_name,
                }
            except Exception as exc:
                errors.append(f"{url} {type(exc).__name__}")
        raise RuntimeError("; ".join(errors[-2:]) or "no response")
    finally:
        try:
            http.close()
        except Exception:
            pass


def proxy_geo(proxy: str) -> dict[str, str]:
    http = sc.build_http(proxy)
    probes = (
        "https://ipapi.co/json/",
        "http://ip-api.com/json/?fields=status,countryCode,regionName,city,zip,timezone,currency,query",
        "https://ipinfo.io/json",
    )
    errors: list[str] = []
    for url in probes:
        try:
            resp = http.get(url, timeout=20)
            if resp.status_code != 200:
                errors.append(f"HTTP {resp.status_code}")
                continue
            data = resp.json() or {}
            country = str(data.get("country") or data.get("country_code") or data.get("countryCode") or "").upper()
            if len(country) != 2:
                continue
            currency = str(data.get("currency") or "").strip().upper()
            if not re.fullmatch(r"[A-Z]{3}", currency):
                currency = ""
            return {
                "ip": str(data.get("ip") or data.get("query") or ""),
                "country": country,
                "currency": currency,
                "country_name": str(data.get("country") or country),
                "region": str(data.get("region") or data.get("region_name") or data.get("regionName") or ""),
                "city": str(data.get("city") or ""),
                "postal": str(data.get("postal") or data.get("zip") or ""),
                "timezone": str(data.get("timezone") or ""),
            }
        except Exception as exc:
            errors.append(type(exc).__name__)
    raise RuntimeError(f"代理地区检测失败：{' / '.join(errors[-3:]) or 'no response'}")


_PROXY_GEO_CACHE: dict[str, tuple[float, dict[str, str]]] = {}
_PROXY_GEO_CACHE_LOCK = threading.Lock()


def proxy_geo_cached(proxy: str, ttl: int = 900) -> dict[str, str]:
    now = time.time()
    # The same pool entry can expose a different exit when the local gateway
    # changes.  Include the first hop in the cache key so a runtime config
    # change cannot reuse a direct/old-chain result.
    cache_key = f"{sc.proxy_pre_proxy() or ''}\x00{proxy}"
    with _PROXY_GEO_CACHE_LOCK:
        cached = _PROXY_GEO_CACHE.get(cache_key)
        if cached and now - cached[0] <= ttl:
            return dict(cached[1])
    data = proxy_geo(proxy)
    with _PROXY_GEO_CACHE_LOCK:
        _PROXY_GEO_CACHE[cache_key] = (now, dict(data))
    return data


def select_paypal_exit_proxy(preferred: str, pool: list[str], scan_limit: int = 24) -> tuple[str, dict[str, str], list[str]]:
    """Pick a proxy whose detected country has an exact OpenAI billing pair."""
    rest = [proxy for proxy in dict.fromkeys(pool) if proxy and proxy != preferred]
    random.SystemRandom().shuffle(rest)
    candidates = ([preferred] if preferred else []) + rest
    candidates = candidates[:max(1, min(int(scan_limit), len(candidates)))]
    if not candidates:
        raise RuntimeError("代理池 2 为空")

    rejected: list[str] = []
    executor = ThreadPoolExecutor(max_workers=min(6, len(candidates)), thread_name_prefix="paypal-geo")
    future_map = {executor.submit(proxy_geo_cached, proxy): proxy for proxy in candidates}
    try:
        for future in as_completed(future_map):
            proxy = future_map[future]
            try:
                geo = future.result()
            except Exception:
                continue
            country = str(geo.get("country") or "").upper()
            if re.fullmatch(r"[A-Z]{2}", country):
                for pending in future_map:
                    if pending is not future:
                        pending.cancel()
                return proxy, geo, rejected
            if country and country not in rejected:
                rejected.append(country)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    summary = "/".join(rejected[:12]) or "未识别"
    raise RuntimeError(
        f"代理池 2 本轮未找到 OpenAI 支持的 PayPal 账单地区；已检测：{summary}。"
        "系统将更换代理继续尝试"
    )


def proxy_country(proxy: str) -> tuple[str, str]:
    data = proxy_geo_cached(proxy)
    return data["country"], data["region"]


def update_checkout_promo(
    http,
    token: str,
    session_id: str,
    processor_entity: str,
    campaign_id: str,
    log,
    *,
    device_id: str = "",
) -> dict:
    body = {
        "checkout_session_id": session_id,
        "processor_entity": processor_entity,
        "plan_name": PLANS["plus"],
        "price_interval": "month",
        "seat_quantity": 1,
        "discount_code": None,
        "promo_campaign": {
            "promo_campaign_id": campaign_id or "plus-1-month-free",
            "is_coupon_from_query_param": False,
        },
    }
    resp = http.post(
        "https://chatgpt.com/backend-api/payments/checkout/update",
        json=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Origin": "https://chatgpt.com",
            "Referer": f"https://chatgpt.com/checkout/{processor_entity}/{session_id}",
            "User-Agent": sc.CHROME_UA,
            "OAI-Language": "zh-CN",
            "OAI-Device-Id": device_id,
            "x-openai-target-path": "/backend-api/payments/checkout/update",
            "x-openai-target-route": "/backend-api/payments/checkout/update",
        },
        timeout=45,
    )
    text = resp.text or ""
    try:
        payload = resp.json() or {}
    except Exception:
        payload = {}
    log(
        f"[promo] checkout/update: {resp.status_code}; "
        f"schema={summarize_checkout_response(payload)}"
    )
    if resp.status_code != 200:
        raise RuntimeError(f"应用 Plus 优惠失败：HTTP {resp.status_code} {text[:300]}")
    return payload


def approve_checkout(
    token: str,
    session_id: str,
    processor: str,
    proxy: str,
    device_id: str,
    did: str,
    *,
    http=None,
    log=lambda _message: None,
) -> dict:
    headers = asyncio.run(sentinel_headers(proxy, "checkout_session_approval", device_id, did))
    http = http or sc.build_http(proxy or None)
    try:
        http.cookies.set("oai-did", did, domain="chatgpt.com")
    except Exception:
        pass
    body = {"checkout_session_id": session_id, "processor_entity": processor}
    resp = http.post(
        "https://chatgpt.com/backend-api/payments/checkout/approve",
        json=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Origin": "https://chatgpt.com",
            "Referer": f"https://chatgpt.com/checkout/{processor}/{session_id}",
            "OAI-Device-Id": device_id,
            "User-Agent": sc.CHROME_UA,
            "OAI-Language": "zh-CN",
            "x-openai-target-path": "/backend-api/payments/checkout/approve",
            "x-openai-target-route": "/backend-api/payments/checkout/approve",
            **headers,
        },
        timeout=40,
    )
    text = resp.text or ""
    log(f"[stripe] manual_approval approve+sentinel: {resp.status_code} {text[:160]}")
    if resp.status_code != 200:
        raise RuntimeError(f"Checkout approve HTTP {resp.status_code}: {text[:300]}")
    try:
        payload = resp.json() or {}
    except Exception:
        payload = {}
    result = str(payload.get("result") or "").lower()
    if result and result != "approved":
        raise RuntimeError(f"manual_approval approve blocked: result={result}")
    return payload


class JobStore:
    def __init__(self):
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.file_lock = threading.RLock()
        self.jobs: dict[str, dict] = {}
        self.worker_limit = max(1, int(os.getenv("PAY153_WORKERS", "20")))
        self.global_rpm = max(1, int(os.getenv("PAY153_GLOBAL_RPM", "20")))
        self.pool = ThreadPoolExecutor(max_workers=self.worker_limit)
        self.pending: deque[tuple[str, dict]] = deque()
        self.start_times: deque[float] = deque()
        self.active_workers = 0
        threading.Thread(target=self._dispatch_loop, name="pay153-dispatcher", daemon=True).start()

    @staticmethod
    def _is_major_log(message: str) -> bool:
        text = str(message or "")
        lowered = text.lower()
        return any(marker in text for marker in (
            "提链尝试", "代理池", "代理校验", "自动设置地区", "计划=",
            "优惠已", "优惠更新", "优惠同步", "金额校验", "今日应付",
            "Checkout 创建", "支付方式已创建", "二维码生成", "链接生成",
            "提交 Checkout approval", "错误：", "本次未成功",
        )) or any(marker in lowered for marker in (
            "init ok", "payment_method:", "manual_approval approve", "checkout/update",
        ))

    def _append_backend_log(self, job_id: str, kind: str, message: str):
        safe_message = re.sub(r"eyJ[A-Za-z0-9_.-]{40,}", "[TOKEN]", str(message))
        day = time.strftime("%Y-%m-%d")
        path = BACKEND_LOG_DIR / day / f"{job_id}.log"
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{kind}] {safe_message}\n"
        try:
            with self.file_lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
        except Exception:
            pass

    def _record_success(self, job_id: str, result: dict):
        """Persist successful link results so batch runs survive restarts."""
        try:
            record = {
                "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "job_id": job_id,
                "combination": "{}-{}".format(
                    str(result.get("entry_country") or "?").upper(),
                    str(result.get("payment_proxy_country") or result.get("checkout_country") or "?").upper(),
                ),
                "attempt": result.get("attempt"),
                "max_attempts": result.get("max_attempts"),
                "plan": result.get("plan") or "",
                "country": result.get("country") or result.get("checkout_country") or "",
                "entry_ip": result.get("entry_ip") or "",
                "entry_country": result.get("entry_country") or "",
                "entry_region": result.get("entry_region") or "",
                "entry_city": result.get("entry_city") or "",
                "payment_ip": result.get("payment_ip") or "",
                "payment_country": result.get("payment_proxy_country") or "",
                "payment_region": result.get("payment_region") or "",
                "payment_city": result.get("payment_city") or "",
                "account_email": result.get("account_email") or "",
                "account_id": result.get("account_id") or "",
                "link_type": result.get("link_type") or "",
                "checkout_amount": result.get("checkout_amount"),
                "currency": result.get("checkout_currency") or result.get("currency") or "",
                "url": result.get("provider_redirect_url") or result.get("paypal_link") or result.get("url") or result.get("link") or result.get("checkout_url") or "",
            }
            path = ROOT / "data" / "success_links.jsonl"
            with self.file_lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                path.chmod(0o600)
            MANAGE_STORE.record_success(record)
        except Exception:
            pass

    def _refresh_queue_locked(self):
        for position, (job_id, _options) in enumerate(self.pending, 1):
            job = self.jobs.get(job_id)
            if not job:
                continue
            job["queue_position"] = position
            job["text"] = f"正在排队，前方 {position - 1} 个任务" if position > 1 else "正在排队，等待执行"
            job["updated_at"] = time.time()

    def _worker_done(self, _future):
        with self.condition:
            self.active_workers = max(0, self.active_workers - 1)
            self.condition.notify_all()

    def _dispatch_loop(self):
        while True:
            with self.condition:
                now = time.time()
                while self.start_times and now - self.start_times[0] >= 60:
                    self.start_times.popleft()

                if not self.pending or self.active_workers >= self.worker_limit:
                    self.condition.wait(timeout=1)
                    continue

                if len(self.start_times) >= self.global_rpm:
                    wait_seconds = max(0.1, 60 - (now - self.start_times[0]))
                    self.condition.wait(timeout=min(wait_seconds, 2))
                    continue

                job_id, options = self.pending.popleft()
                job = self.jobs.get(job_id)
                if not job or job.get("cancel"):
                    if job:
                        job.update(status="cancelled", percent=100, text="任务已停止", queue_position=0)
                    self._refresh_queue_locked()
                    continue

                self.active_workers += 1
                self.start_times.append(now)
                job.update(text="排队完成，即将开始", queue_position=0, dispatched=True, updated_at=now)
                self._refresh_queue_locked()
                future = self.pool.submit(self._run, job_id, options)
                future.add_done_callback(self._worker_done)

    def create(self, options: dict) -> str:
        job_id = uuid.uuid4().hex[:16]
        now = time.time()
        with self.lock:
            expired = [
                key for key, value in self.jobs.items()
                if now - float(value.get("updated_at") or now) > 7200
            ]
            for key in expired:
                self.jobs.pop(key, None)
            if len(self.jobs) >= 500:
                oldest = sorted(self.jobs, key=lambda key: self.jobs[key].get("updated_at", 0))
                for key in oldest[: len(self.jobs) - 499]:
                    self.jobs.pop(key, None)
            self.jobs[job_id] = {
                "id": job_id, "status": "queued", "percent": 2, "text": "任务已创建",
                "logs": [], "result": None, "error": "", "error_code": "", "cancel": False,
                "created_at": now, "updated_at": now, "queue_position": 0, "dispatched": False,
            }
            self.pending.append((job_id, options))
            self._refresh_queue_locked()
            self.condition.notify_all()
        self._append_backend_log(job_id, "SYSTEM", "任务已创建并进入队列")
        return job_id

    def queue_position(self, job_id: str) -> int:
        with self.lock:
            return int((self.jobs.get(job_id) or {}).get("queue_position") or 0)

    def update(self, job_id: str, **fields):
        backend_line = ""
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return
            # A running worker can still be inside a synchronous HTTP request
            # for a few seconds after the user presses stop.  Keep the public
            # state terminal immediately and do not let that worker overwrite
            # `cancelled` with another running/error progress update.
            if (
                job.get("cancel")
                and job.get("status") == "cancelled"
                and fields.get("status") != "cancelled"
            ):
                return
            job.update(fields)
            job["updated_at"] = time.time()
            if "text" in fields or "status" in fields:
                backend_line = f"status={job.get('status')} percent={job.get('percent')} text={job.get('text')}"
        if backend_line:
            self._append_backend_log(job_id, "STATUS", backend_line)

    def log(self, job_id: str, message: str):
        safe = re.sub(r"eyJ[A-Za-z0-9_.-]{40,}", "[TOKEN]", str(message))
        with self.lock:
            job = self.jobs.get(job_id)
            if job is not None:
                job["logs"].append({
                    "time": time.strftime("%H:%M:%S"),
                    "message": safe[:800],
                    "major": self._is_major_log(safe),
                })
                job["logs"] = job["logs"][-1000:]
                job["updated_at"] = time.time()
        self._append_backend_log(job_id, "DETAIL", safe)

    def get(self, job_id: str, public: bool = False) -> dict | None:
        with self.lock:
            job = self.jobs.get(job_id)
            snapshot = json.loads(json.dumps(job, ensure_ascii=False)) if job else None
        if snapshot and public:
            snapshot["logs"] = [item for item in snapshot.get("logs") or [] if item.get("major")]
        return snapshot

    def cancel(self, job_id: str) -> bool:
        with self.condition:
            if job_id not in self.jobs:
                return False
            job = self.jobs[job_id]
            job["cancel"] = True
            if job.get("status") == "queued" and not job.get("dispatched"):
                self.pending = deque((jid, opts) for jid, opts in self.pending if jid != job_id)
                job.update(
                    status="cancelled", percent=100, text="任务已停止",
                    error="任务已停止", queue_position=0,
                )
                self._refresh_queue_locked()
                self._append_backend_log(job_id, "STATUS", "status=cancelled percent=100 text=任务已停止")
            else:
                # Report the terminal state at once.  Cooperative checks in
                # the worker stop the remaining stages at the next boundary.
                job.update(
                    status="cancelled", percent=100, text="任务已停止",
                    error="任务已停止", queue_position=0,
                )
                self._append_backend_log(job_id, "STATUS", "status=cancelled percent=100 text=任务已停止")
            job["updated_at"] = time.time()
            self.condition.notify_all()
            return True

    def cancelled(self, job_id: str) -> bool:
        with self.lock:
            return bool((self.jobs.get(job_id) or {}).get("cancel"))

    def ensure_not_cancelled(self, job_id: str) -> None:
        if self.cancelled(job_id):
            raise InterruptedError("任务已停止")

    def _run(self, job_id: str, options: dict):
        account_lock = checkout_token_lock(str(options.get("token_raw") or ""))
        if not account_lock.acquire(blocking=False):
            message = "同一账号已有提链任务正在运行；并发创建 Checkout 会让旧 Session 失效"
            self.log(job_id, f"错误：RuntimeError: {message}")
            self.update(job_id, status="error", percent=100, text="任务失败", error=message)
            return
        try:
            self._run_locked(job_id, options)
        finally:
            account_lock.release()

    def _run_locked(self, job_id: str, options: dict):
        max_attempts = min(50, max(1, int(options.get("retry_count") or 1)))
        used_pairs: set[tuple[str, str]] = set()
        last_error = ""
        paypal_force_de_fallback = False
        paypal_decline_streak = 0
        account_block_streak = 0
        for attempt in range(1, max_attempts + 1):
            if self.cancelled(job_id):
                self.update(job_id, status="cancelled", percent=100, text="任务已停止", error="任务已停止")
                return
            current = dict(options)
            current["retry_wrapper"] = True
            entry_pool = current["entry_proxies"]
            exit_pool = current.get("exit_proxies") or entry_pool
            pair = None
            for _ in range(40):
                if current.get("link_type") == "pix":
                    proxy = secrets.choice(entry_pool)
                    candidate = (proxy, proxy)
                else:
                    candidate = (secrets.choice(entry_pool), secrets.choice(exit_pool))
                if candidate not in used_pairs or len(used_pairs) >= len(entry_pool) * len(exit_pool):
                    pair = candidate
                    break
            if pair is None:
                pair = (secrets.choice(entry_pool), secrets.choice(exit_pool))
            used_pairs.add(pair)
            current["fixed_entry_proxy"], current["fixed_exit_proxy"] = pair
            if current.get("link_type") == "paypal":
                current["force_paypal_de_fallback"] = paypal_force_de_fallback
                # A zero-due Checkout created with the campaign attached can
                # remove PayPal from Stripe's available payment methods. Keep
                # PayPal in the initial Checkout, then apply the campaign via
                # checkout/update and verify that Stripe reaches amount=0.
                # 所有重试都使用后置优惠；不能在后续轮次重新创建零金额 Checkout。
                current["promo_on_create"] = False
            if current.get("link_type") in {"pix", "upi"}:
                # Alternate both Stripe submission shapes across outer retries.
                # Some Checkout revisions accept a pre-created pm_* while
                # others only complete the local mandate with inline data.
                strategy_cycle = (
                    ("standalone", "late_promo", "inline")
                    if current.get("link_type") == "pix"
                    else ("standalone", "inline", "late_promo")
                )
                current["local_method_strategy"] = strategy_cycle[(attempt - 1) % len(strategy_cycle)]
                # Creating the Checkout at zero due removes PIX/UPI from this
                # merchant's payment_method_types, so local methods keep the
                # mid-flight promotion flow.
                current["promo_on_create"] = False
            if current.get("link_type") == "pix" and current.get("pix_tax_id_auto"):
                auto_kind = current.get("pix_auto_kind") or "cpf"
                kind = ("cpf" if attempt % 2 else "cnpj") if auto_kind == "mixed" else auto_kind
                current["pix_tax_id"] = generate_cnpj() if kind == "cnpj" else generate_cpf()
                current["pix_identity"] = generate_pix_identity(kind)
            self.update(
                job_id, status="running", percent=4,
                text=f"第 {attempt}/{max_attempts} 次尝试：正在准备任务",
                error="",
                error_code="",
            )
            self.log(job_id, f"========== 提链尝试 {attempt}/{max_attempts} ==========")
            if current.get("link_type") == "paypal" and current.get("use_promo"):
                strategy = "Checkout 创建时原生带优惠" if current.get("promo_on_create") else "创建后通过入口线路更新优惠"
                self.log(job_id, f"PayPal 优惠策略：{strategy}")
            self._run_single(job_id, current)
            state = self.get(job_id) or {}
            if state.get("status") in {"done", "cancelled"}:
                if state.get("status") == "done" and isinstance(state.get("result"), dict):
                    result = state["result"]
                    result["attempt"] = attempt
                    result["max_attempts"] = max_attempts
                    self.update(job_id, result=result)
                    self._record_success(job_id, result)
                return
            last_error = str(state.get("error") or "")
            lowered = last_error.lower()
            error_code = str(state.get("error_code") or "")

            # oaics 转换失败是可重试的，需要递增计数器
            if error_code == OAICS_CONVERSION_FAILED_ERROR_CODE:
                current_oaics_retry = current.get("_oaics_retry_count", 0)
                current["_oaics_retry_count"] = current_oaics_retry + 1
                self.log(
                    job_id,
                    f"[oaics 重试 {current_oaics_retry + 1}/{MAX_OAICS_RETRY}] "
                    "换用新代理池重新创建 Checkout"
                )
                # 不计入 max_attempts，直接重试
                time.sleep(1.5)
                continue

            if is_account_block_error(last_error, error_code):
                account_block_streak += 1
                self.log(
                    job_id,
                    f"账号 block 计数 {account_block_streak}/{ACCOUNT_BLOCK_STREAK_LIMIT}："
                    f"{last_error[:180] or 'account blocked'}",
                )
                if account_block_streak >= ACCOUNT_BLOCK_STREAK_LIMIT:
                    block_msg = (
                        f"连续 {account_block_streak} 次明确 account block，任务已停止重试；"
                        "账号建议进入本机冻结，需人工确认后再解冻。"
                    )
                    self.log(job_id, block_msg)
                    self.update(
                        job_id,
                        status="error",
                        percent=100,
                        text="账号连续 block，任务已停止",
                        error=block_msg[:1200],
                        error_code=ACCOUNT_BLOCK_FUSE_ERROR_CODE,
                    )
                    return
            else:
                account_block_streak = 0

            # PayPal：连续同类风控拒绝达到阈值则熔断，避免无脑打满 retry。
            # 账号冷却时长由前端本地账号库承担（工程降频，非官方规定）。
            if current.get("link_type") == "paypal" and is_paypal_risk_decline_error(last_error, error_code):
                paypal_decline_streak += 1
                self.log(
                    job_id,
                    f"PayPal 风控拒绝计数 {paypal_decline_streak}/{PAYPAL_GENERIC_DECLINE_STREAK_LIMIT}："
                    f"{last_error[:180] or 'generic_decline'}"
                )
                if paypal_decline_streak >= PAYPAL_GENERIC_DECLINE_STREAK_LIMIT:
                    fuse_msg = (
                        f"连续 {paypal_decline_streak} 次 PayPal 风控拒绝（多为 generic_decline），"
                        "任务已停止以避免无脑重试。"
                        "建议更换支付代理；账号侧建议冷却约 60 分钟后再试"
                        "（此时长为工程降频策略，非 Stripe/PayPal 官方规定）。"
                    )
                    self.log(job_id, fuse_msg)
                    self.update(
                        job_id,
                        status="error",
                        percent=100,
                        text="PayPal 风控熔断，任务失败",
                        error=fuse_msg[:1200],
                        error_code=PAYPAL_GENERIC_DECLINE_FUSE_ERROR_CODE,
                    )
                    return
            else:
                paypal_decline_streak = 0

            non_retryable = error_code in {
                CHECKOUT_SESSION_CONTRACT_ERROR_CODE,
                PAYPAL_GENERIC_DECLINE_FUSE_ERROR_CODE,
                PROMO_NOT_APPLIED_ERROR_CODE,
                ACCOUNT_BLOCK_FUSE_ERROR_CODE,
            } or any(marker in lowered for marker in (
                "access token", "token_invalidated", "token_expired", "token_revoked", "jwt expired",
                "计划类型", "提取方式", "任务已停止", "所选 paypal 账单地址国家",
            ))
            if non_retryable or attempt >= max_attempts:
                self.update(
                    job_id,
                    status="error",
                    percent=100,
                    text="任务失败",
                    error=last_error[:1200],
                    error_code=error_code or "",
                )
                return
            if (
                current.get("link_type") == "paypal"
                and not paypal_force_de_fallback
                and ("\u672a\u5f00\u653e paypal" in lowered or "\u672a\u5f00\u653epaypal" in lowered)
                and str(current.get("checkout_country") or current.get("country") or "").upper() != "DE"
            ):
                paypal_force_de_fallback = True
                self.log(job_id, "\u5f53\u524d\u56fd\u5bb6 Checkout \u672a\u8fd4\u56de PayPal\uff1b\u540e\u7eed\u5c1d\u8bd5\u81ea\u52a8\u5207\u6362\u5fb7\u56fd DE/EUR \u8d26\u5355")
            self.log(job_id, f"第 {attempt}/{max_attempts} 轮未命中：{last_error[:260] or '上游未返回可用链接'}")
            if options.get("link_type") == "pix":
                self.log(job_id, "正在更换代理与 PIX 资料后重新尝试")
            else:
                self.log(job_id, "正在更换代理后重新尝试")
            time.sleep(min(4, 1 + attempt * 0.35))

    def _run_single(self, job_id: str, options: dict):
        try:
            self.update(job_id, status="running", percent=6, text="解析 Access Token")
            token, meta = extract_access_token(options.pop("token_raw"))
            self.ensure_not_cancelled(job_id)
            provider = options["link_type"]
            country = options["country"]
            entry_pool = options["entry_proxies"]
            exit_pool = entry_pool if provider == "pix" else (options.get("exit_proxies") or entry_pool)
            entry_proxy = options.get("fixed_entry_proxy") or secrets.choice(entry_pool)
            exit_proxy = entry_proxy if provider == "pix" else (options.get("fixed_exit_proxy") or secrets.choice(exit_pool))
            entry_geo: dict[str, str] = {}
            payment_geo: dict[str, str] = {}
            if provider == "hosted":
                self.log(job_id, f"代理池共 {len(entry_pool)} 条，本次已自动选择 1 条")
                try:
                    entry_geo = probe_proxy_identity(entry_proxy)
                except Exception as exc:
                    self.log(job_id, f"入口代理地区记录失败：{type(exc).__name__}")
            elif provider == "pix":
                self.log(job_id, f"代理池 1 共 {len(entry_pool)} 条，本次已自动选择 1 条")
            elif provider == "gopay":
                self.log(
                    job_id,
                    f"代理池 1（优惠更新）共 {len(entry_pool)} 条，"
                    f"代理池 2（印尼支付）共 {len(exit_pool)} 条，本次已分别自动选择",
                )
            else:
                self.log(job_id, f"代理池 1 共 {len(entry_pool)} 条，代理池 2 共 {len(exit_pool)} 条，本次已分别自动选择")
            self.log(
                job_id,
                f"代理链：{sc.proxy_pre_proxy()} 本地第一跳已启用（PAY153_PROXY_PRE_PROXY），代理池条目作为最终出口"
                if sc.proxy_pre_proxy()
                else "代理链：未启用 SOCKS5 本地第一跳，代理池直接连接",
            )
            # Every outer retry creates a brand-new Checkout, so it must also
            # use a fresh browser/device identity.  Within this single attempt
            # the same ids are kept for create -> update -> approve.
            device_id, did = str(uuid.uuid4()), str(uuid.uuid4())

            if provider == "pix":
                self.update(job_id, percent=9, text="第 1/7 步：选择并检测代理")
                entry_geo = proxy_geo_cached(entry_proxy)
                payment_geo = proxy_geo_cached(exit_proxy)
                main_country, main_region = entry_geo.get("country", ""), entry_geo.get("region", "")
                stripe_country, stripe_region = payment_geo.get("country", ""), payment_geo.get("region", "")
                self.log(job_id, f"PIX 代理校验：代理池 1={main_country}/{main_region}")
                if main_country != "BR" or stripe_country != "BR":
                    self.log(
                        job_id,
                        f"PIX 当前代理为 {main_country or '?'} + {stripe_country or '?'}；不限制国家，继续由上游判断支付方式",
                    )
                self.ensure_not_cancelled(job_id)

            promo_requested = options["plan"] == "plus" and options.get("use_promo", False)
            if provider == "paypal":
                self.update(job_id, percent=9, text="第 1/7 步：校验 PayPal 优惠识别代理与支付代理")
                entry_geo = proxy_geo_cached(entry_proxy)
                main_country, main_region = entry_geo.get("country", ""), entry_geo.get("region", "")
                exit_proxy, payment_geo, rejected_countries = select_paypal_exit_proxy(
                    exit_proxy,
                    exit_pool,
                    scan_limit=int(os.getenv("PAYPAL_PROXY_SCAN_LIMIT", "24") or 24),
                )
                payment_country = payment_geo.get("country") or ""
                payment_region = payment_geo.get("region") or ""
                if not payment_country:
                    raise RuntimeError("代理池 2 未检测到国家地区")
                if rejected_countries:
                    self.log(job_id, f"PayPal 已跳过不兼容地区：{'/'.join(rejected_countries[:8])}")
                detected_currency = str(payment_geo.get("currency") or "").upper()
                if options.get("force_paypal_de_fallback"):
                    checkout_country, checkout_currency, currency_source = (
                        "DE", "EUR", f"\u5f53\u524d\u56fd\u5bb6 {payment_country} \u5b9e\u6d4b\u672a\u5f00\u653e PayPal\uff0c\u4f7f\u7528 DE/EUR \u56de\u9000",
                    )
                else:
                    checkout_country, checkout_currency, currency_source = normalize_paypal_checkout_region(
                        payment_country, detected_currency,
                    )
                country = checkout_country
                options["country"] = checkout_country
                options["currency"] = checkout_currency
                options["checkout_country"] = checkout_country
                options["checkout_currency"] = checkout_currency
                options["payment_proxy_country"] = payment_country
                paypal_billing_country = paypal_billing_target_country(
                    checkout_country,
                    payment_country,
                    force_checkout_country=bool(options.get("force_paypal_de_fallback")),
                )
                options["paypal_billing_country"] = paypal_billing_country
                selected_paypal_profile = options.get("paypal_billing_profile") or None
                if selected_paypal_profile:
                    selected_country = str(
                        selected_paypal_profile.get("country") or ""
                    ).strip().upper()
                    if selected_country != paypal_billing_country:
                        raise RuntimeError(
                            f"所选 PayPal 账单地址国家 {selected_country or '未知'} 与本轮实际账单国家 "
                            f"{paypal_billing_country} 不一致；请匹配最终 Checkout 地区或改回自动随机地址"
                        )
                    selection = options.get("paypal_billing_selection") or {}
                    self.log(
                        job_id,
                        f"PayPal 指定账单地址：source={selection.get('kind') or 'manage'} "
                        f"country={paypal_billing_country} id={selection.get('id') or '-'}",
                    )
                self.log(
                    job_id,
                    f"PayPal 代理池 2 地区：{payment_country}/{payment_region}；"
                    f"Checkout={checkout_country}/{checkout_currency}（{currency_source}）",
                )
                if promo_requested and main_country not in {"TR", "JP"}:
                    self.log(job_id, f"PayPal 优惠识别代理当前为 {main_country or '?'}；不限制国家，继续尝试")
                self.ensure_not_cancelled(job_id)
            if provider == "upi":
                self.update(job_id, percent=9, text="第 1/7 步：校验 UPI 优惠识别代理与印度支付代理")
                entry_geo = proxy_geo_cached(entry_proxy)
                payment_geo = proxy_geo_cached(exit_proxy)
                main_country, main_region = entry_geo.get("country", ""), entry_geo.get("region", "")
                payment_country, payment_region = payment_geo.get("country", ""), payment_geo.get("region", "")
                self.log(job_id, f"UPI 代理校验：优惠识别={main_country}/{main_region}，UPI 支付={payment_country}/{payment_region}，账单=IN/INR")
                if promo_requested and main_country not in {"TR", "JP"}:
                    self.log(job_id, f"UPI 优惠识别代理当前为 {main_country or '?'}；不限制国家，继续尝试")
                if payment_country != "IN":
                    self.log(job_id, f"UPI 支付代理当前为 {payment_country or '?'}；不限制国家，继续由上游判断支付方式")
                self.ensure_not_cancelled(job_id)
            if provider == "ideal":
                self.update(job_id, percent=9, text="校验 iDEAL 荷兰支付代理")
                entry_geo = proxy_geo_cached(entry_proxy)
                payment_geo = proxy_geo_cached(exit_proxy)
                main_country, main_region = entry_geo.get("country", ""), entry_geo.get("region", "")
                payment_country, payment_region = payment_geo.get("country", ""), payment_geo.get("region", "")
                self.log(
                    job_id,
                    f"iDEAL 代理校验：入口={main_country}/{main_region}，"
                    f"支付={payment_country}/{payment_region}，账单=NL/EUR",
                )
                if payment_country != "NL":
                    raise RuntimeError(
                        f"iDEAL 支付代理出口为 {payment_country or '未知'}，需要 NL 荷兰出口"
                    )
                self.ensure_not_cancelled(job_id)
            if provider == "gopay":
                self.update(job_id, percent=9, text="校验 Gopay 优惠更新与支付代理")
                entry_geo = proxy_geo_cached(entry_proxy)
                payment_geo = proxy_geo_cached(exit_proxy)
                promo_country, promo_region = entry_geo.get("country", ""), entry_geo.get("region", "")
                payment_country, payment_region = payment_geo.get("country", ""), payment_geo.get("region", "")
                main_country, main_region = promo_country, promo_region
                self.log(
                    job_id,
                    f"Gopay 代理校验：优惠更新={promo_country}/{promo_region}，"
                    f"支付 Checkout={payment_country}/{payment_region}，账单=ID/IDR",
                )
                if promo_country != "TH":
                    self.log(job_id, f"Gopay 优惠更新代理当前为 {promo_country or '?'}；不限制国家，继续尝试")
                if payment_country != "ID":
                    self.log(job_id, f"Gopay 支付代理当前为 {payment_country or '?'}；不限制国家，继续由上游判断支付方式")
                self.ensure_not_cancelled(job_id)
            preflight = {}
            if promo_requested:
                self.update(job_id, percent=12, text="读取入口支付与活动标记")
                preflight = preflight_trial_eligibility(
                    token, meta.get("account_id") or "", entry_proxy, device_id, did,
                    lambda m: self.log(job_id, m),
                )
                detected_campaign = promo_campaign_from_payload(preflight)
                if preflight.get("one_click_trial_eligible") is True:
                    options["promo_marker_eligible"] = True
                if detected_campaign:
                    options["promo_campaign"] = detected_campaign
                    options["promo_campaign_verified"] = True
                    self.log(job_id, f"优惠预检已匹配账号活动：{detected_campaign}")
                self.ensure_not_cancelled(job_id)

            self.update(job_id, percent=18, text="生成 Sentinel 校验")
            payload = checkout_payload(options, meta)
            if provider == "paypal":
                self.log(job_id, f"计划={options['plan']}，方式=paypal，账单={country}/{options['currency']}，PayPal订单={options.get('checkout_country')}/{options.get('checkout_currency')}")
            else:
                self.log(job_id, f"计划={options['plan']}，方式={provider}，地区={country}/{options['currency']}")
            stage2_text = "第 2/7 步：BR 创建 Checkout（首段不带优惠）" if provider == "pix" else (
                (f"第 2/7 步：使用 {country} 代理创建 PayPal Checkout"
                 + ("（原生携带优惠）" if options.get("promo_on_create") else "（稍后更新优惠）"))
                if provider == "paypal" and promo_requested else (
                    "第 2/7 步：使用 IN 代理创建 UPI Checkout" if provider == "upi" else (
                        "第 2/7 步：使用印尼 IP 创建 Gopay Checkout（稍后通过代理池 1 更新优惠）" if provider == "gopay" else "创建 OpenAI Checkout"
                    )
                )
            )
            self.update(job_id, percent=34, text=stage2_text)
            checkout_proxy = exit_proxy if provider in {"paypal", "upi", "ideal", "gopay"} else entry_proxy
            if provider == "pix":
                self.log(
                    job_id,
                    "Stage1 Checkout、优惠更新、Stripe 和 approval 使用同一条 BR 代理"
                    + ("；本轮优惠随 Checkout 创建" if options.get("promo_on_create") else ""),
                )
            elif provider == "paypal" and promo_requested:
                self.log(job_id, f"PayPal 设置：代理池 1 用于优惠检查，代理池 2 创建 {country}/{options['currency']} Checkout")
            elif provider == "upi":
                self.log(job_id, "UPI 设置：代理池 1 用于优惠检查，代理池 2 创建 IN/INR Checkout")
            elif provider == "ideal":
                self.log(job_id, "iDEAL 设置：代理池 2 创建 NL/EUR Checkout，并贯穿 Stripe 支付处理")
            elif provider == "gopay":
                self.log(job_id, "Gopay 设置：代理池 1（TH）仅用于优惠更新，代理池 2（ID）创建 ID/IDR Checkout 并贯穿 Stripe 支付处理")
            elif provider != "hosted":
                self.log(job_id, f"Checkout 将使用所选的 {country} 地区代理")
            created = create_checkout(token, payload, checkout_proxy, device_id, did, lambda m: self.log(job_id, m))
            self.ensure_not_cancelled(job_id)
            self.update(job_id, percent=44, text="Checkout 创建完成，正在准备支付方式")
            checkout_data = created["data"]
            chatgpt_http = created["http"]
            stage1_campaign = promo_campaign_from_payload(checkout_data)
            if checkout_data.get("one_click_trial_eligible") is True:
                options["promo_marker_eligible"] = True
            if stage1_campaign:
                options["promo_campaign"] = stage1_campaign
                options["promo_campaign_verified"] = True
                self.log(job_id, f"Checkout 已返回活动标识：{stage1_campaign}")
            provider_chatgpt_http = chatgpt_http
            promo_chatgpt_http = chatgpt_http
            if provider in {"paypal", "upi", "ideal", "gopay"}:
                promo_chatgpt_http = sc.build_http(entry_proxy)
                try:
                    promo_chatgpt_http.cookies.set("oai-did", did, domain="chatgpt.com")
                    for cookie_name, cookie_value in chatgpt_http.cookies.get_dict().items():
                        promo_chatgpt_http.cookies.set(cookie_name, cookie_value, domain="chatgpt.com")
                    promo_chatgpt_http.get("https://chatgpt.com/", headers={"User-Agent": sc.CHROME_UA}, timeout=25)
                except Exception as exc:
                    self.log(job_id, f"{provider.upper()} 优惠线路暖身提示：{type(exc).__name__}")
                if provider == "paypal":
                    self.log(job_id, f"PayPal 支付处理使用代理池 2（{country}）")
                elif provider == "upi":
                    self.log(job_id, "UPI 支付处理使用代理池 2（IN）")
                elif provider == "gopay":
                    self.log(job_id, "Gopay 优惠更新使用代理池 1（TH），支付处理使用代理池 2（ID）")
                else:
                    self.log(job_id, "iDEAL 优惠更新使用代理池 1，NL/EUR Checkout 与 Stripe 使用代理池 2")
            session_id = checkout_data.get("checkout_session_id") or ""
            has_oaics_session = bool(
                is_openai_checkout_session_id(session_id)
                or is_openai_checkout_session_id(checkout_data.get("openai_checkout_session_id"))
            )
            oaics_payment_methods = (
                extract_checkout_payment_methods(checkout_data)
                if has_oaics_session
                else []
            )
            options["_oaics_payment_methods"] = oaics_payment_methods
            if session_id and not is_stripe_checkout_session_id(session_id):
                # Do not pass an oaics_* OpenAI-owned ID to Stripe's
                # /v1/payment_pages/<id>/init.  If OpenAI does not expose a
                # nested cs_* after update, keep the session on OpenAI's
                # official managed checkout route instead.
                if not is_openai_checkout_session_id(session_id):
                    raise checkout_session_contract_error(checkout_data, "Checkout")
                processor_entity = str(
                    checkout_data.get("processor_entity")
                    or checkout_data.get("processor")
                    or ""
                ).strip()
                if not processor_entity:
                    processor_entity = sc._entity_from_return_url(
                        str(checkout_data.get("return_url") or checkout_data.get("url") or "")
                    )
                if not processor_entity:
                    raise RuntimeError(
                        "Checkout 返回 OpenAI 内部 Session，但缺少 processor_entity，无法换取 Stripe Session"
                    )
                openai_session_id = str(session_id)
                materialized: dict[str, Any] = {}
                if promo_requested:
                    self.log(
                        job_id,
                        f"Checkout 返回 OpenAI 内部 Session {openai_session_id[:32]}，"
                        "先更新优惠并识别后续 Checkout 协议",
                    )
                    materialized = update_checkout_promo(
                        promo_chatgpt_http,
                        token,
                        openai_session_id,
                        processor_entity,
                        options.get("promo_campaign") or "plus-1-month-free",
                        lambda m: self.log(job_id, m),
                        device_id=device_id,
                    )
                    if materialized.get("success") is False:
                        raise RuntimeError("checkout/update 未接受本次优惠更新")

                nested_session = materialized.get("checkout_session")
                if isinstance(nested_session, dict):
                    for key in ("publishable_key", "processor_entity", "return_url", "url"):
                        if nested_session.get(key):
                            checkout_data[key] = nested_session[key]
                for method in extract_checkout_payment_methods(materialized):
                    if method not in oaics_payment_methods:
                        oaics_payment_methods.append(method)
                options["_oaics_payment_methods"] = oaics_payment_methods
                self.log(
                    job_id,
                    "OAICS 支付方式识别（脱敏）："
                    f"{oaics_payment_methods or ['未暴露']}；"
                    f"PayPal={'可用' if 'paypal' in oaics_payment_methods else '未确认'}",
                )
                resolved_session_id = extract_stripe_checkout_session_id(materialized)
                if resolved_session_id:
                    checkout_data["openai_checkout_session_id"] = openai_session_id
                    session_id = resolved_session_id
                    checkout_data["checkout_session_id"] = session_id
                    options["promo_preapplied"] = promo_requested
                    self.log(
                        job_id,
                        f"Checkout Session 已映射为 Stripe {session_id[:32]}，后续 Stripe 请求使用该 ID",
                    )
                else:
                    # An OAICS response may advertise PayPal without exposing
                    # a Stripe payment_page.  Do not invent a private
                    # custom_payment_method/start request from that capability
                    # flag; keep the browser-backed fallback until a verified
                    # request/response contract is available.
                    # oaics_* 转换失败，检查是否已重试过
                    current_oaics_retry = options.get("_oaics_retry_count", 0)
                    if current_oaics_retry < MAX_OAICS_RETRY:
                        # 抛出异常触发重试
                        self.log(
                            job_id,
                            f"oaics_* 转换失败（第 {current_oaics_retry + 1} 次尝试），"
                            f"将自动重试新流程（剩余 {MAX_OAICS_RETRY - current_oaics_retry} 次）"
                        )
                        raise OaicsConversionFailedError(
                            f"oaics_* 转换为 cs_live_* 失败，需要重试（已尝试 {current_oaics_retry + 1} 次）"
                        )
                    else:
                        # 重试次数耗尽，回退到 OpenAI 托管结账页
                        managed_url = openai_managed_checkout_url(
                            materialized or checkout_data,
                            openai_session_id,
                            processor_entity,
                        ) or openai_managed_checkout_url(
                            checkout_data,
                            openai_session_id,
                            processor_entity,
                        )
                        if not managed_url:
                            raise checkout_session_contract_error(
                                materialized or checkout_data,
                                "OpenAI managed Checkout",
                            )
                        self.log(
                            job_id,
                            f"oaics_* 转换失败且已重试 {MAX_OAICS_RETRY} 次，"
                            "切换为 OpenAI 托管结账页，需要浏览器完成"
                        )
                        session_id = openai_session_id
                        checkout_data["checkout_session_id"] = session_id
                        checkout_data["openai_checkout_session_id"] = session_id
                        checkout_data["checkout_url"] = managed_url
                        checkout_data["processor_entity"] = processor_entity
                        options["openai_managed_checkout"] = True
                        options["promo_update_accepted"] = bool(
                            promo_requested and materialized.get("success") is True
                        )
                        self.log(
                            job_id,
                            "当前为 OpenAI 托管 oaics_* Checkout；已切换官方结账页，"
                            "不再调用 Stripe payment_page",
                        )
            if not session_id and provider != "hosted":
                raise RuntimeError("Checkout 未返回 Stripe Session ID")
            if self.cancelled(job_id):
                raise InterruptedError("任务已停止")

            result: dict[str, Any] = {
                "plan": options["plan"],
                "link_type": provider,
                "checkout_session_id": session_id,
                "checkout_url": checkout_data.get("checkout_url") or "",
                "account_email": meta.get("email") or "",
                "account_id": meta.get("account_id") or "",
                "country": country,
                "currency": options["currency"],
                "checkout_country": options.get("checkout_country") or country,
                "checkout_currency": options.get("checkout_currency") or options["currency"],
                "entry_proxy_pool_size": len(entry_pool),
                "exit_proxy_pool_size": len(exit_pool) if provider not in {"hosted", "pix"} else 0,
                "proxy_mode": "single_chain" if provider == "pix" else ("entry_only" if provider == "hosted" else "dual_chain"),
                "promo_requested": promo_requested,
                "promo_applied": None,
                "promo_campaign_used": options.get("promo_campaign") or "plus-1-month-free",
                "entry_trial_eligible": preflight.get("one_click_trial_eligible"),
                "checkout_trial_eligible": checkout_data.get("one_click_trial_eligible"),
                "entry_one_click_marker": preflight.get("one_click_trial_eligible"),
                "checkout_one_click_marker": checkout_data.get("one_click_trial_eligible"),
                "promotion_eligibility_decided_by": "checkout_approve",
                "entry_country": str(entry_geo.get("country") or locals().get("main_country") or "").upper(),
                "entry_ip": str(entry_geo.get("ip") or ""),
                "entry_region": str(entry_geo.get("region") or locals().get("main_region") or ""),
                "entry_city": str(entry_geo.get("city") or ""),
                "payment_proxy_country": str(options.get("payment_proxy_country") or payment_geo.get("country") or locals().get("payment_country") or "").upper(),
                "payment_ip": str(payment_geo.get("ip") or ""),
                "payment_region": str(payment_geo.get("region") or locals().get("payment_region") or ""),
                "payment_city": str(payment_geo.get("city") or ""),
                "oaics_retry_count": options.get("_oaics_retry_count", 0),
                "oaics_retry_success": bool(
                    options.get("_oaics_retry_count", 0) > 0 and is_stripe_checkout_session_id(session_id)
                ),
                "oaics_payment_method_types": list(options.get("_oaics_payment_methods") or []),
                "oaics_paypal_available": "paypal" in (options.get("_oaics_payment_methods") or []),
            }
            if promo_requested:
                checkout_trial = checkout_data.get("one_click_trial_eligible")
                self.log(
                    job_id,
                    "支付标记（仅供诊断）：入口 one_click={}，Stage1 one_click={}".format(
                        preflight.get("one_click_trial_eligible"), checkout_trial
                    ),
                )
                if checkout_trial is False:
                    self.log(
                        job_id,
                        "Stage1 one_click 标记为 false；该字段不代表活动资格，继续以金额与 approval 结果判定",
                    )
            if options.get("openai_managed_checkout"):
                if provider not in {"paypal", "hosted"}:
                    raise checkout_session_contract_error(
                        checkout_data,
                        f"{provider.upper()} OpenAI managed Checkout",
                    )
                managed_url = str(checkout_data.get("checkout_url") or "")
                result.update({
                    "provider": provider,
                    "provider_redirect_url": managed_url,
                    "checkout_url": managed_url,
                    "checkout_flow": "openai_managed",
                    "requires_browser": True,
                    "processor_entity": checkout_data.get("processor_entity") or "",
                    "promo_update_accepted": bool(options.get("promo_update_accepted")),
                    "promotion_eligibility_decided_by": "official_checkout_page",
                })
                if promo_requested and options.get("promo_update_accepted"):
                    self.log(
                        job_id,
                        "OpenAI 已接受优惠更新；最终金额和 PayPal 可用性请在官方结账页确认",
                    )
                else:
                    self.log(job_id, "PayPal 可用性和最终金额请在 OpenAI 官方结账页确认")
                done_text = (
                    "OpenAI 官方 PayPal 结账页已生成"
                    if provider == "paypal"
                    else "OpenAI 官方支付长链已生成"
                )
                self.update(job_id, percent=100, text=done_text, status="done", result=result)
                return
            if provider == "hosted":
                self.update(job_id, percent=56, text="正在检测官方长链金额")
                if not session_id:
                    if promo_requested:
                        raise sc.PromoNotAppliedError("官方长链未返回 Stripe Session ID，优惠金额校验失败")
                    self.update(job_id, percent=100, text="支付长链生成完成", status="done", result=result)
                    return

                hosted_stripe_http = sc.build_http(entry_proxy)
                hosted_profile = sc._profile(country)
                hosted_pk = str(checkout_data.get("publishable_key") or "") or sc.verify_pk(
                    hosted_stripe_http, session_id, lambda m: self.log(job_id, m)
                )
                hosted_init, hosted_version, hosted_ctx = sc.init_checkout(
                    hosted_stripe_http, session_id, hosted_pk, hosted_profile, lambda m: self.log(job_id, m)
                )
                hosted_processor = (
                    str(checkout_data.get("processor_entity") or "")
                    or sc._entity_from_return_url(hosted_ctx.get("return_url") or hosted_init.get("return_url") or "")
                    or "openai_llc"
                )
                hosted_amount = hosted_ctx.get("checkout_amount")
                try:
                    hosted_zero = int(str(hosted_amount)) == 0
                except (TypeError, ValueError):
                    hosted_zero = str(hosted_amount).strip() in {"0", "0.0", "0.00"}

                if promo_requested and not hosted_zero:
                    self.update(job_id, percent=68, text="正在应用优惠并同步金额")
                    update_checkout_promo(
                        chatgpt_http,
                        token,
                        session_id,
                        hosted_processor,
                        options.get("promo_campaign") or "plus-1-month-free",
                        lambda m: self.log(job_id, m),
                        device_id=device_id,
                    )
                    for sync_attempt in range(6):
                        time.sleep(1.5 if sync_attempt else 0.8)
                        hosted_init, hosted_version, hosted_ctx = sc.init_checkout(
                            hosted_stripe_http, session_id, hosted_pk, hosted_profile, lambda m: self.log(job_id, m)
                        )
                        hosted_amount = hosted_ctx.get("checkout_amount")
                        self.log(job_id, f"官方长链优惠同步检查 {sync_attempt + 1}/6：amount={hosted_amount}")
                        try:
                            hosted_zero = int(str(hosted_amount)) == 0
                        except (TypeError, ValueError):
                            hosted_zero = str(hosted_amount).strip() in {"0", "0.0", "0.00"}
                        if hosted_zero:
                            break

                hosted_billing = default_billing(country, meta.get("email") or "")
                sc.update_tax_region(
                    hosted_stripe_http,
                    session_id,
                    hosted_pk,
                    hosted_version,
                    hosted_ctx,
                    hosted_billing,
                    hosted_profile,
                    lambda m: self.log(job_id, m),
                )
                hosted_amount = hosted_ctx.get("checkout_amount")
                try:
                    hosted_zero = int(str(hosted_amount)) == 0
                except (TypeError, ValueError):
                    hosted_zero = str(hosted_amount).strip() in {"0", "0.0", "0.00"}
                result.update({
                    "checkout_amount": hosted_amount,
                    "promo_applied": hosted_zero if promo_requested else None,
                    "payment_method_types": hosted_ctx.get("payment_method_types") or [],
                    "processor_entity": hosted_processor,
                    "stripe_publishable_key": hosted_pk,
                })
                if promo_requested and not hosted_zero:
                    raise sc.PromoNotAppliedError(f"官方长链优惠未生效：Stripe 今日应付 amount={hosted_amount}")
                if promo_requested:
                    self.log(job_id, "官方长链金额校验通过：Stripe 今日应付 amount=0")
                else:
                    self.log(job_id, f"官方长链金额检测完成：Stripe 今日应付 amount={hosted_amount}")
                self.update(job_id, percent=100, text="支付长链生成完成", status="done", result=result)
                return

            stage3_text = "第 3/7 步：正在初始化 PIX" if provider == "pix" else (
                "第 3/7 步：正在初始化 PayPal" if provider == "paypal" and promo_requested else f"正在初始化 {provider.upper()}"
            )
            self.update(job_id, percent=56, text=stage3_text)
            billing_geo = None
            if provider == "paypal" and str(options.get("payment_proxy_country") or "").upper() == country:
                billing_geo = payment_geo
            selected_paypal_profile = (
                options.get("paypal_billing_profile") or None
                if provider == "paypal" else None
            )
            paypal_billing_country = (
                str(options.get("paypal_billing_country") or country).upper()
                if provider == "paypal" else ""
            )
            main_billing_profile = options.get("billing_profile") or None
            if selected_paypal_profile and paypal_billing_country == country:
                main_billing_profile = selected_paypal_profile
            billing = default_billing(
                country,
                meta.get("email") or "",
                options.get("pix_tax_id") or "",
                billing_geo,
                real_random=(provider == "paypal"),
                billing_profile=main_billing_profile,
                require_profile=provider == "gopay",
            )
            if billing.get("_address_source") == "manual_profile":
                selected_address = billing.get("address") or {}
                self.log(
                    job_id,
                    "账单档案：source=manual_profile country={} city={} state={} postal={} line1={}".format(
                        selected_address.get("country") or "-",
                        selected_address.get("city") or "-",
                        selected_address.get("state") or "-",
                        selected_address.get("postal_code") or "-",
                        selected_address.get("line1") or "-",
                    ),
                )
            if provider == "paypal":
                selected_address = billing.get("address") or {}
                self.log(
                    job_id,
                    "PayPal 本轮 OpenAI 账单：source={}，国家={}，城市={}，邮编={}，地点={}".format(
                        billing.get("_address_source") or "unknown",
                        selected_address.get("country") or country,
                        selected_address.get("city") or "-",
                        selected_address.get("postal_code") or "-",
                        billing.get("_place_name") or "公开场所",
                    ),
                )
            paypal_payment_billing = None
            if provider == "paypal":
                paypal_proxy_country = str(
                    options.get("payment_proxy_country") or country
                ).upper()
                if paypal_billing_country == country:
                    if paypal_proxy_country != country:
                        self.log(
                            job_id,
                            f"PayPal 账单统一：代理出口={paypal_proxy_country}，"
                            f"最终 Checkout/PayPal={country}；使用 {paypal_billing_country} 完整账单地址",
                        )
                else:
                    # Only create a separate PaymentMethod billing object when
                    # the final PayPal billing country really differs from the
                    # OpenAI Checkout country.  A missing profile means auto
                    # selection; never pass {} into default_billing().
                    paypal_payment_billing = default_billing(
                        paypal_billing_country,
                        meta.get("email") or "",
                        geo=payment_geo,
                        real_random=True,
                        billing_profile=selected_paypal_profile,
                    )
                    paypal_address = paypal_payment_billing.get("address") or {}
                    self.log(
                        job_id,
                        f"PayPal separated billing: OpenAI={country}/{options.get('currency')}, "
                        f"PayPal={paypal_billing_country}, proxy={paypal_proxy_country}, "
                        f"source={paypal_payment_billing.get('_address_source') or 'unknown'}, "
                        f"city={paypal_address.get('city') or '-'}, "
                        f"postal={paypal_address.get('postal_code') or '-'}",
                    )
            promotion_billing = None
            if provider == "paypal" and promo_requested:
                promotion_country = str(main_country or "BR").upper()
                promotion_billing = default_billing(
                    promotion_country,
                    meta.get("email") or "",
                )
                self.log(
                    job_id,
                    f"PayPal 地区：优惠更新={promotion_country}，Stripe/PayPal 账单与 merchant 快照={country}",
                )
            if provider == "pix":
                identity = options.get("pix_identity") or {}
                if identity:
                    billing["name"] = identity.get("name") or billing.get("name")
                    billing["email"] = identity.get("email") or billing.get("email")
                    address = billing.setdefault("address", {})
                    for key in ("line1", "city", "state", "postal_code"):
                        if identity.get(key):
                            address[key] = identity[key]
                    if identity.get("source") == "brasilapi_cnpj":
                        self.log(job_id, f"PIX 已匹配 CNPJ 登记主体：{billing.get('name')} / {address.get('state')}")
                    elif str(identity.get("source") or "").startswith("generated_"):
                        generated_kind = str(identity.get("source")).removeprefix("generated_").upper()
                        self.log(job_id, f"PIX 本轮已自动生成 {generated_kind}、持有人/企业名称及巴西地址")
            stripe_http = sc.build_http(exit_proxy)

            progress_mark = 62

            def advance_progress(percent: int, text: str):
                nonlocal progress_mark
                self.ensure_not_cancelled(job_id)
                if percent > progress_mark:
                    progress_mark = percent
                    self.update(job_id, percent=percent, text=text)

            def provider_log(message: str):
                self.log(job_id, message)
                lowered_message = message.lower()
                if "init ok" in lowered_message:
                    advance_progress(64, "支付方式初始化完成")
                elif "checkout/update" in lowered_message or "优惠更新完成" in message:
                    advance_progress(72, "优惠已应用，正在确认金额")
                elif "tax_region" in lowered_message:
                    advance_progress(78, "金额确认完成，正在提交账单信息")
                elif "snapshot billing" in lowered_message:
                    advance_progress(84, "账单信息已提交")
                elif "payment_method" in lowered_message:
                    advance_progress(88, "支付方式已创建")
                elif "manual_approval" in lowered_message or "approve:" in lowered_message:
                    advance_progress(92, "正在确认支付请求")
                elif "poll" in lowered_message:
                    advance_progress(96, "正在获取最终结果")

            def approve_cb(processor: str):
                self.ensure_not_cancelled(job_id)
                advance_progress(90, "正在确认支付请求")
                self.log(job_id, "提交 Checkout approval")
                approve_checkout(
                    token,
                    session_id,
                    processor,
                    checkout_proxy,
                    device_id,
                    did,
                    http=provider_chatgpt_http,
                    log=provider_log,
                )
                self.ensure_not_cancelled(job_id)

            def apply_promo_cb(processor: str):
                self.ensure_not_cancelled(job_id)
                if provider == "pix":
                    self.log(job_id, "第 4/7 步：初始化已确认 PIX，开始应用优惠")
                elif provider == "paypal":
                    self.log(job_id, "PayPal 已确认可用，正在应用优惠")
                elif provider == "upi":
                    self.log(job_id, "UPI 已确认可用，正在应用优惠")
                elif provider == "ideal":
                    self.log(job_id, "iDEAL 已确认可用，正在通过代理池 1 提交优惠；最终以 Stripe 今日应付金额为准")
                elif provider == "gopay":
                    self.log(job_id, "Gopay 已确认可用，正在通过代理池 1 提交优惠")
                advance_progress(70, "正在应用优惠")
                campaign = options.get("promo_campaign") or "plus-1-month-free"
                response = update_checkout_promo(
                    promo_chatgpt_http,
                    token,
                    session_id,
                    processor,
                    campaign,
                    provider_log,
                    device_id=device_id,
                )
                self.ensure_not_cancelled(job_id)
                return response

            self.update(job_id, percent=62, text="正在生成支付结果")
            provider_result = stripe_to_provider(
                stripe_http,
                session_id,
                provider,
                billing=billing,
                promotion_billing=promotion_billing,
                payment_billing=paypal_payment_billing,
                payment_http=stripe_http if paypal_payment_billing else None,
                country=options.get("checkout_country") or country,
                chatgpt_http=provider_chatgpt_http,
                access_token=token,
                stage1=checkout_data,
                # PayPal 保持原协议的 Bearer approval；PIX/UPI 才使用带
                # Sentinel 的 callback。PayPal approval 返回 approved 后仍
                # 卡住时，额外 Sentinel 上下文会让批准结果与 Stripe
                # submission 不同步。
                approve_callback=None if provider == "paypal" else approve_cb,
                apply_promo_callback=(
                    apply_promo_cb
                    if provider in {"pix", "paypal", "upi", "ideal", "gopay"}
                    and promo_requested
                    and not options.get("promo_preapplied")
                    else None
                ),
                ideal_bank=options.get("ideal_bank", ""),
                require_zero_due=promo_requested,
                local_method_strategy=options.get("local_method_strategy") or "standalone",
                log=provider_log,
            )
            self.ensure_not_cancelled(job_id)
            self.update(job_id, percent=98, text="结果已生成，正在整理页面")
            result.update(provider_result)
            # Display the currency Stripe actually returned instead of only
            # echoing the requested currency.  This also makes automatic
            # proxy-region adaptation observable in the result panel/API.
            if provider_result.get("checkout_currency"):
                result["currency"] = str(provider_result["checkout_currency"]).upper()
                result["checkout_currency"] = result["currency"]
            done_text = "第 7/7 步：PIX 二维码生成完成" if provider == "pix" else (
                "第 7/7 步：PayPal agreements/approve 链接生成完成" if provider == "paypal" else (
                    "第 7/7 步：Gopay 支付链接生成完成" if provider == "gopay" else f"{provider.upper()} 提取完成"
                )
            )

            # 记录成功节点信息（用于后续优化代理选择）
            if provider == "gopay" and (entry_proxy or exit_proxy):
                try:
                    import datetime
                    success_info = []
                    if entry_proxy:
                        promo_country = entry_geo.get("country") or ""
                        promo_region = entry_geo.get("region") or ""
                        success_info.append(f"代理池1（优惠更新）={promo_country}/{promo_region}")
                    if exit_proxy:
                        payment_country = payment_geo.get("country") or ""
                        payment_region = payment_geo.get("region") or ""
                        success_info.append(f"代理池2（支付）={payment_country}/{payment_region}")
                    success_info.append(f"时间={datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                    success_info.append(f"尝试次数={attempt}")
                    self.log(job_id, f"✅ Gopay 成功节点：{'; '.join(success_info)}")
                except Exception:
                    pass  # 记录失败不影响主流程

            self.update(job_id, percent=100, text=done_text, status="done", result=result)
        except InterruptedError as exc:
            self.update(job_id, status="cancelled", percent=100, text=str(exc), error=str(exc))
        except Exception as exc:
            raw_error = str(exc)
            error_text = raw_error
            lowered = raw_error.lower()
            error_code = str(getattr(exc, "error_code", "") or "")
            if "token_invalidated" in lowered or "authentication token has been invalidated" in lowered:
                error_text = "Access Token 已失效，请重新登录 ChatGPT 获取新的 Session JSON 或 AT。"
            elif "token_expired" in lowered or "jwt expired" in lowered:
                error_text = "Access Token 已过期，请重新登录 ChatGPT 获取新的 Session JSON 或 AT。"
            elif "not_eligible" in lowered:
                error_text = "当前账号未开放所选套餐或支付通道。"
            elif "cannot combine currencies" in lowered:
                error_text = "该账号已有其他币种的活跃结账会话，请等待原会话释放，或更换账号后再生成当前币种链接。"
            elif "amount_too_small" in lowered:
                error_text = "当前地区换算后的结账金额低于支付提供商下限，请提高 Codex 积分数量后重试。"
            self.log(job_id, f"错误：{type(exc).__name__}: {error_text}")
            if error_code == CHECKOUT_SESSION_CONTRACT_ERROR_CODE:
                self.update(
                    job_id,
                    status="error",
                    percent=100,
                    text="Checkout 接口协议已变化，已停止重复重试",
                    error=error_text[:1200],
                    error_code=error_code,
                )
            elif error_code == PROMO_NOT_APPLIED_ERROR_CODE:
                self.update(
                    job_id,
                    status="error",
                    percent=100,
                    text="优惠未生效，已停止重试",
                    error=error_text[:1200],
                    error_code=error_code,
                )
            elif options.get("retry_wrapper"):
                self.update(job_id, status="running", percent=8, text="本次未成功，正在更换代理重试", error=error_text[:1200])
            else:
                self.update(job_id, status="error", percent=100, text="任务失败", error=error_text[:1200])


class IpTaskLimiter:
    def __init__(self, limit: int = 3, window_seconds: int = 60):
        self.limit = max(1, int(limit))
        self.window_seconds = max(1, int(window_seconds))
        self.lock = threading.RLock()
        self.events: defaultdict[str, deque[float]] = defaultdict(deque)

    def acquire(self, ip: str) -> tuple[bool, int]:
        now = time.time()
        with self.lock:
            bucket = self.events[ip]
            while bucket and now - bucket[0] >= self.window_seconds:
                bucket.popleft()
            if len(bucket) >= self.limit:
                retry_after = max(1, int(self.window_seconds - (now - bucket[0]) + 0.999))
                return False, retry_after
            bucket.append(now)
            if len(self.events) > 10000:
                stale = [key for key, values in self.events.items() if not values or now - values[-1] > self.window_seconds * 2]
                for key in stale[:2000]:
                    self.events.pop(key, None)
            return True, 0


def request_client_ip() -> str:
    remote = str(request.remote_addr or "").strip()
    if remote in {"127.0.0.1", "::1"}:
        return str(request.headers.get("X-Real-IP") or remote).strip()
    return remote or "unknown"


STORE = JobStore()
IP_TASK_LIMITER = IpTaskLimiter(
    limit=int(os.getenv("PAY153_IP_RPM", "3")),
    window_seconds=60,
)


@app.after_request
def security_headers(resp):
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


def manage_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not MANAGE_PASSWORD:
            return jsonify({"error": "管理中心尚未启用，请设置 PAY153_MANAGE_PASSWORD"}), 503
        if not session.get("manage_authenticated"):
            return jsonify({"error": "需要先登录管理中心"}), 401
        return view(*args, **kwargs)
    return wrapped


def _manage_payload() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def _safe_log_message(value: str) -> str:
    value = re.sub(r"(?i)(bearer\s+)[^\s]+", r"\1[TOKEN]", str(value or ""))
    return re.sub(r"eyJ[A-Za-z0-9_.-]{40,}", "[TOKEN]", value)


_PUBLIC_ADDRESS_ID_FIELDS = (
    "country", "name", "line1", "city", "state", "postal_code",
)


def _public_address_id(address: dict[str, Any]) -> str:
    canonical = "\x1f".join(
        str(address.get(field) or "").strip()
        for field in _PUBLIC_ADDRESS_ID_FIELDS
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]


def _builtin_public_address_items(country: str = "") -> list[dict[str, Any]]:
    from billing_address_resolver import _BUILTIN_PUBLIC_ADDRESSES

    wanted_country = str(country or "").strip().upper()
    rows: list[dict[str, Any]] = []
    countries = [wanted_country] if wanted_country else sorted(_BUILTIN_PUBLIC_ADDRESSES)
    for country_code in countries:
        for raw in _BUILTIN_PUBLIC_ADDRESSES.get(country_code, []):
            item = dict(raw)
            item["country"] = str(item.get("country") or country_code).upper()
            item["id"] = _public_address_id(item)
            rows.append(item)
    return rows


def _find_builtin_public_address(address_id: str) -> dict[str, Any]:
    address_id = str(address_id or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{20}", address_id):
        return {}
    return next(
        (item for item in _builtin_public_address_items() if item["id"] == address_id),
        {},
    )


def _paypal_billing_country_options(
    manual_profiles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    from billing_address_resolver import _BUILTIN_PUBLIC_ADDRESSES

    manual_counts: dict[str, int] = defaultdict(int)
    for item in manual_profiles:
        country = str(item.get("country") or "").strip().upper()
        if country:
            manual_counts[country] += 1
    countries = sorted(set(_BUILTIN_PUBLIC_ADDRESSES) | set(manual_counts))
    return [
        {
            "country": country,
            "builtin_count": len(_BUILTIN_PUBLIC_ADDRESSES.get(country, [])),
            "manual_count": manual_counts.get(country, 0),
        }
        for country in countries
    ]


def _resolve_paypal_billing_selection(
    raw_selection: dict[str, Any],
) -> tuple[dict[str, str], dict[str, Any]]:
    kind = str(raw_selection.get("kind") or "").strip().lower()
    requested_country = str(raw_selection.get("country") or "").strip().upper()

    if kind == "manage_profile":
        try:
            profile_id = int(raw_selection.get("id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("所选 Manage 账单档案 ID 不正确") from exc
        item = MANAGE_STORE.get_billing_profile(profile_id, reveal=True)
        if not item:
            raise ValueError("所选 Manage 账单档案不存在")
        country = str(item.get("country") or "").strip().upper()
        profile = dict(item.get("profile") or {})
        profile["country"] = country
        selection_id: int | str = profile_id
    elif kind == "builtin_address":
        item = _find_builtin_public_address(str(raw_selection.get("id") or ""))
        if not item:
            raise ValueError("所选内置公共地址不存在或已更新")
        country = str(item.get("country") or "").strip().upper()
        profile = {
            "name": item.get("name") or "",
            "email": "",
            "line1": item.get("line1") or "",
            "line2": item.get("line2") or "",
            "city": item.get("city") or "",
            "state": item.get("state") or "",
            "postal_code": item.get("postal_code") or "",
            "country": country,
        }
        selection_id = item["id"]
    else:
        raise ValueError("PayPal 账单地址来源不正确")

    if requested_country and requested_country != country:
        raise ValueError(
            f"所选地址国家 {country or '未知'} 与下拉国家 {requested_country} 不一致"
        )
    if not re.fullmatch(r"[A-Z]{2}", country):
        raise ValueError("所选 Manage 账单档案缺少有效国家代码")
    normalized = normalize_billing_profile(profile, country, require_complete=True)
    return normalized, {
        "kind": kind,
        "id": selection_id,
        "country": country,
    }


@app.get("/manage")
def manage_page():
    return send_from_directory(app.static_folder, "manage.html")


@app.get("/api/manage/session")
def manage_session():
    return jsonify({
        "configured": bool(MANAGE_PASSWORD),
        "authenticated": bool(session.get("manage_authenticated")),
        "path": "/manage",
    })


@app.post("/api/manage/login")
def manage_login():
    if not MANAGE_PASSWORD:
        return jsonify({"error": "管理中心尚未启用，请设置 PAY153_MANAGE_PASSWORD"}), 503
    password = str(_manage_payload().get("password") or "")
    if not secrets.compare_digest(password, MANAGE_PASSWORD):
        session.pop("manage_authenticated", None)
        return jsonify({"error": "管理密码不正确"}), 401
    session["manage_authenticated"] = True
    session["manage_login_at"] = int(time.time())
    return jsonify({"ok": True})


@app.post("/api/manage/logout")
def manage_logout():
    session.pop("manage_authenticated", None)
    session.pop("manage_login_at", None)
    return jsonify({"ok": True})


@app.get("/api/manage/summary")
@manage_required
def manage_summary():
    return jsonify(MANAGE_STORE.summary())


@app.route("/api/manage/proxy-pools", methods=["GET", "POST"])
@manage_required
def manage_proxy_pools():
    if request.method == "GET":
        return jsonify({"items": MANAGE_STORE.list_proxy_pools(request.args.get("country", ""), request.args.get("rail", ""))})
    payload = _manage_payload()
    try:
        proxies = normalize_proxy_pool(payload.get("proxies") or payload.get("proxy_data") or "", "代理池")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not proxies:
        return jsonify({"error": "代理池至少需要一条代理"}), 400
    payload["proxies"] = proxies
    try:
        return jsonify({"item": MANAGE_STORE.upsert_proxy_pool(payload)}), 201
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/manage/proxy-pools/<int:pool_id>", methods=["GET", "PUT", "DELETE"])
@manage_required
def manage_proxy_pool_detail(pool_id: int):
    if request.method == "GET":
        item = MANAGE_STORE.get_proxy_pool(pool_id, reveal=request.args.get("reveal") == "1")
        return jsonify(item) if item else (jsonify({"error": "代理池不存在"}), 404)
    if request.method == "DELETE":
        return jsonify({"ok": MANAGE_STORE.delete_proxy_pool(pool_id)})
    payload = _manage_payload()
    payload["id"] = pool_id
    existing = MANAGE_STORE.get_proxy_pool(pool_id)
    if not existing:
        return jsonify({"error": "代理池不存在"}), 404
    payload.setdefault("external_key", existing.get("external_key", ""))
    try:
        payload["proxies"] = normalize_proxy_pool(payload.get("proxies") or payload.get("proxy_data") or "", "代理池")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not payload["proxies"]:
        return jsonify({"error": "代理池至少需要一条代理"}), 400
    item = MANAGE_STORE.upsert_proxy_pool(payload)
    return jsonify({"item": item}) if item else (jsonify({"error": "代理池不存在"}), 404)


@app.route("/api/manage/billing-profiles", methods=["GET", "POST"])
@manage_required
def manage_billing_profiles():
    if request.method == "GET":
        country = request.args.get("country", "")
        return jsonify({
            "items": MANAGE_STORE.list_billing_profiles(country, request.args.get("rail", "")),
        })
    payload = _manage_payload()
    try:
        return jsonify({"item": MANAGE_STORE.upsert_billing_profile(payload)}), 201
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400



@app.route("/api/manage/billing-profiles/<int:profile_id>", methods=["GET", "PUT", "DELETE"])
@manage_required
def manage_billing_profile_detail(profile_id: int):
    if request.method == "GET":
        item = MANAGE_STORE.get_billing_profile(profile_id, reveal=request.args.get("reveal") == "1")
        return jsonify(item) if item else (jsonify({"error": "账单档案不存在"}), 404)
    if request.method == "DELETE":
        return jsonify({"ok": MANAGE_STORE.delete_billing_profile(profile_id)})
    payload = _manage_payload()
    payload["id"] = profile_id
    try:
        existing = MANAGE_STORE.get_billing_profile(profile_id, reveal=True)
        if not existing:
            return jsonify({"error": "账单档案不存在"}), 404
        return jsonify({"item": MANAGE_STORE.upsert_billing_profile(payload)})
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/manage/paypal-billing-options")
@manage_required
def manage_paypal_billing_options():
    country = str(request.args.get("country") or "").strip().upper()
    if country and not re.fullmatch(r"[A-Z]{2}", country):
        return jsonify({"error": "国家/地区需要使用两位国家代码"}), 400

    all_manual_profiles = MANAGE_STORE.list_billing_profiles()
    manual_profiles = [
        item for item in all_manual_profiles
        if country and str(item.get("country") or "").upper() == country
    ]
    return jsonify({
        "country": country,
        "countries": _paypal_billing_country_options(all_manual_profiles),
        "manual_profiles": manual_profiles,
        "builtin_addresses": _builtin_public_address_items(country) if country else [],
    })


@app.route("/api/manage/asn-recommendations", methods=["GET", "PUT"])
@manage_required
def manage_asn_recommendations():
    if request.method == "GET":
        return jsonify({"items": MANAGE_STORE.list_asn_recommendations(request.args.get("country", ""))})
    payload = _manage_payload()
    try:
        return jsonify({"item": MANAGE_STORE.upsert_asn_recommendation(payload)})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/manage/builtin-addresses", methods=["GET"])
@manage_required
def manage_builtin_addresses():
    """获取内置公共地址库"""
    country = request.args.get("country", "").upper()
    address_type = request.args.get("type", "").lower()
    all_addresses = _builtin_public_address_items()
    library_total = len(all_addresses)
    addresses = _builtin_public_address_items(country) if country else all_addresses

    # 按地址类型筛选
    if address_type:
        addresses = [addr for addr in addresses if addr.get("type", "") == address_type]

    # 统计信息
    countries = sorted({address.get("country", "") for address in all_addresses if address.get("country")})
    type_counts = {}
    for addr in addresses:
        addr_type = addr.get("type", "unknown")
        type_counts[addr_type] = type_counts.get(addr_type, 0) + 1

    return jsonify({
        "success": True,
        "addresses": addresses,
        "total": len(addresses),
        "library_total": library_total,
        "countries": countries,
        "type_counts": type_counts,
    })


@app.get("/api/manage/success-records")
@manage_required
def manage_success_records():
    try:
        limit = int(request.args.get("limit", "100"))
    except ValueError:
        limit = 100
    items = MANAGE_STORE.list_success_records(
        limit=limit,
        country=request.args.get("country", ""),
        link_type=request.args.get("link_type", ""),
        query=request.args.get("q", ""),
    )
    return jsonify({"items": items})


@app.get("/api/manage/logs")
@manage_required
def manage_logs():
    day = str(request.args.get("day") or time.strftime("%Y-%m-%d"))[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return jsonify({"error": "日志日期格式应为 YYYY-MM-DD"}), 400
    job_id = str(request.args.get("job_id") or "").strip()[:120]
    query = str(request.args.get("q") or "").strip().lower()[:160]
    try:
        limit = max(1, min(500, int(request.args.get("limit", "200"))))
    except ValueError:
        limit = 200
    directory = BACKEND_LOG_DIR / day
    if job_id and not re.fullmatch(r"[A-Za-z0-9._-]+", job_id):
        return jsonify({"error": "Job ID 格式不正确"}), 400
    paths = [directory / f"{job_id}.log"] if job_id else sorted(directory.glob("*.log"), reverse=True)
    line_re = re.compile(r"^(?P<time>[^ ]+ [^ ]+) \[(?P<kind>[^]]+)\] (?P<message>.*)$")
    items: list[dict[str, str]] = []
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            match = line_re.match(line)
            if match:
                item = {
                    "time": match.group("time"),
                    "kind": match.group("kind"),
                    "job_id": path.stem,
                    "message": _safe_log_message(match.group("message")),
                }
            else:
                item = {"time": "", "kind": "LOG", "job_id": path.stem, "message": _safe_log_message(line)}
            if query and query not in json.dumps(item, ensure_ascii=False).lower():
                continue
            items.append(item)
    items.sort(key=lambda item: (item.get("time") or "", item.get("job_id") or ""), reverse=True)
    items = items[:limit]
    return jsonify({"day": day, "items": items})


@app.post("/api/manage/import-local")
@manage_required
def manage_import_local():
    payload = _manage_payload()
    imported = {"proxy_pools": 0, "billing_profiles": 0, "asn_regions": 0}

    proxy_config = payload.get("proxy_profiles")
    if isinstance(proxy_config, dict):
        proxy_groups: list[tuple[str, dict[str, Any]]] = []
        default = proxy_config.get("default")
        if isinstance(default, dict):
            proxy_groups.append(("default", default))
        profiles = proxy_config.get("profiles")
        if isinstance(profiles, dict):
            proxy_groups.extend((str(rail), value) for rail, value in profiles.items() if isinstance(value, dict))
        for rail, group in proxy_groups:
            for pool_kind in ("entry", "exit"):
                raw = group.get(pool_kind)
                if not raw:
                    continue
                try:
                    proxies = normalize_proxy_pool(raw, f"{rail} {pool_kind}")
                except ValueError:
                    continue
                if not proxies:
                    continue
                MANAGE_STORE.upsert_proxy_pool({
                    "external_key": f"browser:{rail}:{pool_kind}",
                    "name": f"{rail} · {pool_kind}",
                    "rail": "shared" if rail == "default" else rail,
                    "pool_kind": pool_kind,
                    "proxies": proxies,
                    "enabled": True,
                })
                imported["proxy_pools"] += 1

    billing_config = payload.get("billing_profiles")
    if isinstance(billing_config, dict) and isinstance(billing_config.get("profiles"), dict):
        for profile_key, profile in billing_config["profiles"].items():
            if not isinstance(profile, dict):
                continue
            parts = str(profile_key).split(":", 1)
            MANAGE_STORE.upsert_billing_profile({
                **profile,
                "profile_key": str(profile_key),
                "rail": parts[0],
                "country": parts[1] if len(parts) > 1 else profile.get("country", ""),
                "source": "browser-local",
            })
            imported["billing_profiles"] += 1

    asn_config = payload.get("asn_recommendations")
    if isinstance(asn_config, dict) and isinstance(asn_config.get("regions"), dict):
        for country, recommendation in asn_config["regions"].items():
            if not isinstance(recommendation, dict):
                continue
            try:
                MANAGE_STORE.upsert_asn_recommendation({"country": country, **recommendation})
                imported["asn_regions"] += 1
            except ValueError:
                continue
    return jsonify({"ok": True, "imported": imported})


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/health")
def health():
    return jsonify({
        "ok": True,
        "service": "pay153",
        "time": int(time.time()),
        "proxy_pre_proxy_enabled": bool(sc.proxy_pre_proxy()),
    })


@app.get("/api/config")
def config():
    return jsonify({
        "plans": list(PLANS),
        "link_types": ["hosted", "paypal", "ideal", "upi", "pix", "gopay"],
        "country_currency": COUNTRY_CURRENCY,
        "provider_defaults": PROVIDER_DEFAULTS,
        "proxy_policy": {
            "entry_required": True,
            "exit_required_for": ["paypal", "ideal", "upi"],
            "single_chain_for": ["pix"],
            "max_per_pool": 500,
            "selection": "random_per_job",
        },
        "retry_policy": {"min": 1, "max": 50, "default_pix": 10, "default_other": 3},
        "pix_identity_policy": {"default": "cpf", "auto_kinds": ["cpf", "mixed", "cnpj"], "regenerate_each_attempt": True},
        "task_limits": {
            "global_rpm": STORE.global_rpm,
            "per_ip_rpm": IP_TASK_LIMITER.limit,
            "queue_enabled": True,
            "workers": STORE.worker_limit,
        },
        "manage": {
            "enabled": bool(MANAGE_PASSWORD),
            "path": "/manage",
            "storage": "sqlite",
        },
    })


@app.post("/api/proxy-probe")
def proxy_probe():
    data = request.get_json(silent=True) or {}
    pool_label = str(data.get("pool") or "代理池").strip()[:40] or "代理池"
    try:
        proxies = normalize_proxy_pool(data.get("proxies"), pool_label)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not proxies:
        return jsonify({"error": f"{pool_label}至少填写 1 条代理"}), 400

    selected = secrets.choice(proxies)
    candidates = [selected]
    rest = [proxy for proxy in proxies if proxy != selected]
    random.SystemRandom().shuffle(rest)
    candidates.extend(rest[:2])
    identity: dict[str, str] | None = None
    last_error: Exception | None = None
    attempts = 0
    for candidate in candidates:
        attempts += 1
        try:
            identity = probe_proxy_identity(candidate)
            selected = candidate
            break
        except Exception as exc:
            last_error = exc
    if identity is None:
        error_type = type(last_error).__name__ if last_error else "RuntimeError"
        return jsonify({
            "error": f"{pool_label}随机检测失败：{error_type}",
            "attempts": attempts,
        }), 502
    return jsonify({
        "ok": True,
        "pool": pool_label,
        "pool_size": len(proxies),
        "attempts": attempts,
        "selected_index": proxies.index(selected) + 1,
        **identity,
    })


@app.post("/api/checkout")
def start_checkout():
    data = request.get_json(silent=True) or {}
    plan = str(data.get("plan") or "plus").lower()
    link_type = str(data.get("link_type") or "hosted").lower()
    if plan not in PLANS:
        return jsonify({"error": "计划类型不正确"}), 400
    if link_type not in {"hosted", "paypal", "ideal", "upi", "pix", "gopay"}:
        return jsonify({"error": "提取方式不正确"}), 400
    defaults = PROVIDER_DEFAULTS.get(link_type, {})
    country = str(data.get("country") or defaults.get("country") or "US").upper()
    requested_currency = str(data.get("currency") or defaults.get("currency") or COUNTRY_CURRENCY.get(country, "USD")).upper()
    currency, _currency_source = normalize_checkout_currency(country, requested_currency)
    entry_raw = data.get("entry_proxies")
    if entry_raw is None:
        entry_raw = data.get("entry_proxy") or data.get("api_proxy") or data.get("proxy") or ""
    exit_raw = data.get("exit_proxies")
    if exit_raw is None:
        exit_raw = data.get("exit_proxy") or data.get("payment_proxy") or ""
    if not entry_raw:
        return jsonify({"error": "请填写 Checkout 入口代理"}), 400
    if link_type not in {"hosted", "pix"} and not exit_raw:
        return jsonify({"error": "当前支付路径需要填写支付出口代理"}), 400
    try:
        entry_proxies = normalize_proxy_pool(entry_raw, "入口代理")
        exit_proxies = normalize_proxy_pool(exit_raw, "出口代理") if exit_raw and link_type != "pix" else []
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not entry_proxies:
        return jsonify({"error": "入口代理至少填写 1 条"}), 400
    if link_type not in {"hosted", "pix"} and not exit_proxies:
        return jsonify({"error": "出口代理至少填写 1 条"}), 400
    raw_pix_tax_id = re.sub(r"\D", "", str(data.get("pix_tax_id") or ""))[:14] if link_type == "pix" else ""
    try:
        retry_count = min(50, max(1, int(data.get("retry_count") or (10 if link_type == "pix" else 3))))
    except (TypeError, ValueError):
        return jsonify({"error": "重试次数需要填写 1-50 的整数"}), 400
    pix_identity: dict[str, str] = {}
    if link_type == "pix":
        manual_identity = {
            "name": str(data.get("pix_name") or "").strip()[:160],
            "email": str(data.get("pix_email") or "").strip()[:200],
            "line1": str(data.get("pix_line1") or "").strip()[:180],
            "city": str(data.get("pix_city") or "").strip()[:100],
            "state": str(data.get("pix_state") or "").strip()[:40],
            "postal_code": str(data.get("pix_postal_code") or "").strip()[:30],
        }
        if len(raw_pix_tax_id) == 14:
            try:
                pix_identity.update(lookup_cnpj_identity(raw_pix_tax_id))
            except Exception as exc:
                if not manual_identity["name"]:
                    return jsonify({"error": f"CNPJ 登记信息查询失败：{exc}"}), 400
        pix_identity.update({key: value for key, value in manual_identity.items() if value})
    if link_type == "gopay" and country != "ID":
        return jsonify({"error": "Gopay Checkout 国家必须为 ID/印尼"}), 400

    paypal_billing_profile: dict[str, str] = {}
    paypal_billing_selection: dict[str, Any] = {}
    raw_billing_selection = data.get("billing_selection")
    if raw_billing_selection is not None and not isinstance(raw_billing_selection, dict):
        return jsonify({"error": "PayPal 账单地址选择参数不正确"}), 400
    selection_kind = str(
        (raw_billing_selection or {}).get("kind") or ""
    ).strip().lower()
    if selection_kind not in {"", "auto"}:
        if link_type != "paypal":
            return jsonify({"error": "Manage 账单地址选择仅用于 PayPal"}), 400
        if not MANAGE_PASSWORD:
            return jsonify({"error": "管理中心尚未启用，请设置 PAY153_MANAGE_PASSWORD"}), 503
        if not session.get("manage_authenticated"):
            return jsonify({"error": "需要先登录管理中心才能使用所选账单地址"}), 401
        try:
            paypal_billing_profile, paypal_billing_selection = (
                _resolve_paypal_billing_selection(raw_billing_selection or {})
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
    try:
        billing_profile = normalize_billing_profile(
            data.get("billing_profile"),
            country,
            require_complete=link_type == "gopay",
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    options = {
        "token_raw": str(data.get("token") or ""),
        "plan": plan,
        "link_type": link_type,
        "country": country,
        "currency": currency,
        "checkout_country": country,
        "checkout_currency": currency,
        "entry_proxies": entry_proxies,
        "exit_proxies": entry_proxies if link_type == "pix" else exit_proxies,
        "use_promo": bool(data.get("use_promo", True)) if plan == "plus" else False,
        "promo_campaign": str(data.get("promo_campaign") or "") if plan == "plus" else "",
        "promo_code": str(data.get("promo_code") or "") if plan == "team" else "",
        "workspace_name": str(data.get("workspace_name") or "")[:80],
        "workspace_id": str(data.get("workspace_id") or "")[:120],
        "seat_quantity": min(999, max(2, int(data.get("seat_quantity") or 5))),
        "price_interval": "year" if data.get("price_interval") == "year" else "month",
        "credit_quantity": min(100000, max(1, int(data.get("credit_quantity") or 13))),
        "ideal_bank": str(data.get("ideal_bank") or "")[:40] if link_type == "ideal" else "",
        "pix_tax_id": raw_pix_tax_id,
        "pix_tax_id_auto": link_type == "pix" and not raw_pix_tax_id,
        "pix_auto_kind": str(data.get("pix_auto_kind") or "cpf").lower()
            if str(data.get("pix_auto_kind") or "cpf").lower() in {"mixed", "cpf", "cnpj"} else "cpf",
        "pix_identity": pix_identity,
        "billing_profile": billing_profile,
        "paypal_billing_profile": paypal_billing_profile,
        "paypal_billing_selection": paypal_billing_selection,
        "retry_count": retry_count,
    }
    if not options["token_raw"].strip():
        return jsonify({"error": "请填写 Access Token 或 Session JSON"}), 400
    if link_type == "pix" and options["pix_tax_id"] and len(options["pix_tax_id"]) not in {11, 14}:
        return jsonify({"error": "PIX 需要填写 11 位 CPF 或 14 位 CNPJ"}), 400
    client_ip = request_client_ip()
    allowed, retry_after = IP_TASK_LIMITER.acquire(client_ip)
    if not allowed:
        response = jsonify({
            "error": f"当前 IP 每分钟最多创建 {IP_TASK_LIMITER.limit} 个任务，请在 {retry_after} 秒后重试。",
            "retry_after": retry_after,
            "limit": IP_TASK_LIMITER.limit,
        })
        response.headers["Retry-After"] = str(retry_after)
        return response, 429
    job_id = STORE.create(options)
    return jsonify({
        "ok": True,
        "job_id": job_id,
        "queue_position": STORE.queue_position(job_id),
        "global_rpm": STORE.global_rpm,
        "ip_rpm": IP_TASK_LIMITER.limit,
    }), 202


@app.get("/api/checkout-progress")
def checkout_progress():
    job = STORE.get(str(request.args.get("job_id") or ""), public=True)
    if not job:
        if LEGACY_SERVICE_BASE:
            try:
                legacy = requests.get(
                    f"{LEGACY_SERVICE_BASE}/api/checkout-progress",
                    params={"job_id": str(request.args.get("job_id") or "")},
                    timeout=8,
                )
                return app.response_class(
                    response=legacy.content,
                    status=legacy.status_code,
                    content_type=legacy.headers.get("content-type", "application/json"),
                )
            except Exception:
                pass
        return jsonify({"error": "任务不存在"}), 404
    return jsonify(job)


@app.post("/api/checkout-cancel")
def checkout_cancel():
    data = request.get_json(silent=True) or {}
    job_id = str(data.get("job_id") or "")
    ok = STORE.cancel(job_id)
    if not ok and LEGACY_SERVICE_BASE:
        try:
            legacy = requests.post(
                f"{LEGACY_SERVICE_BASE}/api/checkout-cancel",
                json={"job_id": job_id},
                timeout=8,
            )
            return app.response_class(
                response=legacy.content,
                status=legacy.status_code,
                content_type=legacy.headers.get("content-type", "application/json"),
            )
        except Exception:
            pass
    return jsonify({"ok": ok}), 200 if ok else 404


if __name__ == "__main__":
    app.run(host=os.getenv("PAY153_HOST", "127.0.0.1"), port=int(os.getenv("PAY153_PORT", "18082")), threaded=True)
