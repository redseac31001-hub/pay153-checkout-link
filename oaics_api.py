"""OAICS PayPal 的本地 HTTP 协议适配。

OAICS 的标准 PayPal 路径不是把 ``oaics_*`` 转成 Stripe ``cs_*``，而是复用
官方 Checkout 页面背后的 HTTP 链：读取 session、提交账单税区、初始化
Stripe Elements Session、创建 confirmation token、调用 ChatGPT confirm，
必要时再确认 Stripe PaymentIntent/SetupIntent，最后解析 PayPal BA 跳转。

所有请求复用当前支付会话和 9697 前置代理，不启动浏览器。动态 Sentinel、
hCaptcha 和部署证明只使用当前任务实际生成/配置的值，不把 HAR 中的一次性值
写死到代码里。
"""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any, Callable
from urllib.parse import parse_qsl, urlsplit

import stripe_checkout as sc


STRIPE_CONFIRMATION_TOKENS_URL = f"{sc.STRIPE_API}/v1/confirmation_tokens"
STRIPE_ELEMENTS_SESSIONS_URL = f"{sc.STRIPE_API}/v1/elements/sessions"
OAICS_CONFIRM_URL = "https://chatgpt.com/backend-api/payments/checkout/confirm"
OAICS_CHECKOUT_BASE = "https://chatgpt.com/backend-api/payments/checkout"
OAICS_TAXES_URL = f"{OAICS_CHECKOUT_BASE}/taxes"
DEFAULT_STRIPE_JS_VERSION = "4dae3e22af"
DEFAULT_CHATGPT_CLIENT_VERSION = "prod-1827e06d85a24a9606e4199dd07d869724cd0915"
DEFAULT_CHATGPT_CLIENT_BUILD_NUMBER = "8953813"

_OAICS_WRAPPER_KEYS = (
    "checkout_session",
    "checkoutSession",
    "session",
    "checkout",
    "data",
    "result",
    "payload",
    "response",
    "checkout_state",
    "checkoutState",
    "checkout_snapshot",
    "checkoutSnapshot",
    "state",
    "taxes",
    "checkout_data",
)
_OAICS_AMOUNT_PATHS = (
    ("checkout_amount_minor",),
    ("total_summary", "due"),
    ("totalSummary", "due"),
    ("invoice", "amount_due"),
    ("invoice", "amountDue"),
    ("amount_due",),
    ("amountDue",),
    ("amount_total",),
    ("amountTotal",),
    ("total", "total"),
    ("total", "due"),
    ("total", "taxInclusive"),
    ("total", "taxInclusiveAmount"),
)
_PM_REDIRECT_RE = re.compile(
    r"https://pm-redirects\.stripe\.com/authorize/[^\s\"'<>\\]+",
    re.IGNORECASE,
)

BA_URL_RE = re.compile(
    r"https://(?:www\.)?paypal\.com/agreements/approve\?[^\s\"'<>]+",
    re.IGNORECASE,
)


class OaicsApiError(RuntimeError):
    """OAICS 本地接口调用失败。"""


def _payload(response) -> dict[str, Any]:
    try:
        value = response.json()
        return value if isinstance(value, dict) else {}
    except Exception:
        try:
            value = json.loads(response.text or "{}")
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk_dicts(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_dicts(nested)


def _find_string(
    value: Any,
    names: tuple[str, ...],
    *,
    prefixes: tuple[str, ...] = (),
) -> str:
    for item in _walk_dicts(value):
        for name in names:
            candidate = item.get(name)
            if not isinstance(candidate, str):
                continue
            candidate = candidate.strip()
            if candidate and (not prefixes or candidate.startswith(prefixes)):
                return candidate
    return ""


def _profile_language(country: str, language: str = "") -> str:
    value = str(language or "").strip()
    if value:
        return value
    return str(
        (getattr(sc, "_profile", lambda _country: {})(country) or {}).get(
            "browser_language"
        )
        or "en-US"
    )


def _oaics_user_agent() -> str:
    return str(os.getenv("PAY153_OAICS_USER_AGENT") or sc.CHROME_UA).strip()


def _chrome_client_hints(user_agent: str) -> tuple[str, str]:
    match = re.search(r"Chrome/(\d+)(?:\.([\d.]+))?", user_agent or "")
    major = match.group(1) if match else "136"
    full = f"{major}.{match.group(2)}" if match and match.group(2) else major
    return (
        f'"Chromium";v="{major}", "Google Chrome";v="{major}", "Not.A/Brand";v="99"',
        f'"Chromium";v="{full}", "Google Chrome";v="{full}", "Not.A/Brand";v="99.0.0.0"',
    )


def oaics_context_headers(
    *,
    country: str,
    device_id: str,
    oai_session_id: str = "",
    referer: str = "https://chatgpt.com/",
    language: str = "",
) -> dict[str, str]:
    """构造 ChatGPT Checkout 页面使用的稳定上下文头。

    ``oai-web-deployment-attestation``、``oai-telemetry`` 和 observation
    标记都是运行时字段，只有显式配置时才发送；不能把 HAR 中的旧值复用到
    新任务。Authorization 由调用方按接口用途单独添加。
    """
    browser_language = _profile_language(country, language)
    short_language = browser_language.split("-", 1)[0]
    user_agent = _oaics_user_agent()
    sec_ch_ua, sec_ch_ua_full = _chrome_client_hints(user_agent)
    session_id = str(oai_session_id or "").strip() or str(uuid.uuid4())
    headers = {
        "Accept-Language": f"{browser_language},{short_language};q=0.9,en;q=0.8",
        "Referer": referer,
        "User-Agent": user_agent,
        "sec-ch-ua": sec_ch_ua,
        "sec-ch-ua-full-version-list": sec_ch_ua_full,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "OAI-Language": browser_language,
        "oai-client-version": str(
            os.getenv("PAY153_OAI_CLIENT_VERSION") or DEFAULT_CHATGPT_CLIENT_VERSION
        ).strip(),
        "oai-client-build-number": str(
            os.getenv("PAY153_OAI_CLIENT_BUILD_NUMBER")
            or DEFAULT_CHATGPT_CLIENT_BUILD_NUMBER
        ).strip(),
    }
    if device_id:
        headers["oai-device-id"] = str(device_id)
    if session_id:
        headers["oai-session-id"] = session_id
    for env_name, header_name in (
        ("PAY153_OAI_WEB_DEPLOYMENT_ATTESTATION", "oai-web-deployment-attestation"),
        ("PAY153_OAI_TELEMETRY", "oai-telemetry"),
        ("PAY153_OAI_CLIENT_OBSERVATION", "x-oai-is-client-observation"),
    ):
        value = str(os.getenv(env_name) or "").strip()
        if value:
            headers[header_name] = value
    return headers


def _oaics_headers(
    *,
    access_token: str,
    country: str,
    device_id: str,
    oai_session_id: str,
    referer: str,
    language: str = "",
    route: str = "",
) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {access_token}" if access_token else "",
        "Accept": "application/json",
        "Origin": "https://chatgpt.com",
        **oaics_context_headers(
            country=country,
            device_id=device_id,
            oai_session_id=oai_session_id,
            referer=referer,
            language=language,
        ),
    }
    if not access_token:
        headers.pop("Authorization", None)
    if route:
        headers["x-openai-target-path"] = route
        headers["x-openai-target-route"] = route
    return headers


def _response_detail(response) -> str:
    payload = _payload(response)
    error = payload.get("error") if isinstance(payload, dict) else {}
    if isinstance(error, dict):
        detail = error.get("message") or error.get("code") or error.get("type")
        if detail:
            return str(detail)
    return str(getattr(response, "text", "") or "")[:300]


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _normalize_url(value: str) -> str:
    return (
        str(value or "")
        .replace("\\/", "/")
        .replace("\\u0026", "&")
        .replace("&amp;", "&")
    )


def validate_paypal_ba_url(value: str) -> bool:
    try:
        parsed = urlsplit(_normalize_url(value))
    except Exception:
        return False
    if (parsed.hostname or "").lower() not in {"paypal.com", "www.paypal.com"}:
        return False
    if parsed.path.rstrip("/").lower() != "/agreements/approve":
        return False
    token = dict(parse_qsl(parsed.query, keep_blank_values=True)).get("ba_token") or ""
    return bool(re.fullmatch(r"BA-[A-Za-z0-9_-]+", str(token), re.IGNORECASE))


def extract_paypal_ba_url(value: Any) -> str:
    for item in _strings(value):
        text = _normalize_url(item)
        for match in BA_URL_RE.finditer(text):
            candidate = text[match.start() : match.end()].rstrip(".,)")
            if validate_paypal_ba_url(candidate):
                return candidate
    return ""


def _address_fields(billing: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    address = billing.get("address") if isinstance(billing, dict) else {}
    if not isinstance(address, dict):
        address = {}
    return str(billing.get("name") or ""), address


def _payment_method_types(methods: list[str] | None) -> list[str]:
    values = [str(item or "").strip().lower() for item in (methods or [])]
    values = [item for item in values if item]
    if "paypal" in values:
        values.remove("paypal")
    result = ["paypal"]
    for item in values or ["card", "link"]:
        if item not in result:
            result.append(item)
    return result


def _ctx_value(checkout_data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = checkout_data.get(key)
        if value not in (None, ""):
            return str(value)
    nested = checkout_data.get("checkout_session")
    if isinstance(nested, dict):
        for key in keys:
            value = nested.get(key)
            if value not in (None, ""):
                return str(value)
    return ""


def _merge_payloads(*payloads: Any) -> dict[str, Any]:
    """合并多个上游快照，保留每个非空顶层字段。"""
    merged: dict[str, Any] = {}
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key, value in payload.items():
            if value not in (None, "", [], {}):
                merged[key] = value
    return merged


def oaics_payment_method_types(value: Any) -> list[str]:
    methods: list[str] = []
    seen: set[str] = set()
    for item in _walk_dicts(value):
        candidates = item.get("payment_method_types")
        if candidates is None:
            candidates = item.get("paymentMethodTypes")
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if isinstance(candidate, dict):
                candidate = candidate.get("type")
            method = str(candidate or "").strip().lower()
            if method and method not in seen:
                seen.add(method)
                methods.append(method)
    return methods


def _oaics_amount_value(value: Any) -> int | None:
    if isinstance(value, dict):
        for key in ("minorUnitsAmount", "minor_units_amount", "amount"):
            if value.get(key) is not None:
                return _oaics_amount_value(value.get(key))
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value or "").strip()
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return None


def _nested_path(value: Any, path: tuple[str, ...]) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def oaics_amount_observations(value: Any) -> list[tuple[str, int]]:
    """提取应付金额字段；不把商品单价当作待付金额。"""
    observations: list[tuple[str, int]] = []
    visited: set[int] = set()

    def visit(payload: Any, prefix: str = "") -> None:
        if not isinstance(payload, dict) or id(payload) in visited:
            return
        visited.add(id(payload))
        for path in _OAICS_AMOUNT_PATHS:
            amount = _oaics_amount_value(_nested_path(payload, path))
            if amount is not None:
                observations.append((f"{prefix}{'.'.join(path)}", amount))
        for key in _OAICS_WRAPPER_KEYS:
            nested = payload.get(key)
            if isinstance(nested, dict):
                visit(nested, f"{prefix}{key}.")

    visit(value)
    return list(dict.fromkeys(observations))


def verify_oaics_zero_snapshot(value: Any, *, currency: str = "") -> int:
    observations = oaics_amount_observations(value)
    if not observations:
        raise OaicsApiError(
            "OAICS 未返回可核验的应付金额，不能确认优惠已归零"
            + (f"（currency={str(currency).upper()}）" if currency else "")
        )
    nonzero = [(label, amount) for label, amount in observations if amount != 0]
    if nonzero:
        detail = ", ".join(f"{label}={amount}" for label, amount in nonzero[:6])
        raise OaicsApiError(f"OAICS 优惠金额未归零：{detail}")
    return 0


def resolve_publishable_key(checkout_data: dict[str, Any]) -> str:
    """优先使用 Checkout 返回的 pk，最后才使用已有公开 key 映射。"""
    value = _find_string(
        checkout_data,
        ("publishable_key", "stripe_publishable_key", "pk"),
        prefixes=("pk_",),
    )
    if value:
        return value
    configured = str(os.getenv("PAY153_OAICS_PUBLISHABLE_KEY") or "").strip()
    if configured.startswith("pk_"):
        return configured
    processor = str(
        checkout_data.get("processor_entity")
        or checkout_data.get("processor")
        or ""
    ).lower()
    if processor in {"openai_llc", "openai_ie"}:
        known = getattr(sc, "KNOWN_PUBLISHABLE_KEYS", {}) or {}
        for value in known.values():
            if str(value).startswith("pk_"):
                return str(value)
    return ""


def build_confirmation_token_data(
    *,
    publishable_key: str,
    session_id: str,
    billing: dict[str, Any],
    currency: str,
    payment_methods: list[str] | None = None,
    checkout_data: dict[str, Any] | None = None,
    hcaptcha_token: str = "",
) -> dict[str, str]:
    """构造 HAR 中 confirmation_tokens 的非浏览器部分。"""
    checkout_data = checkout_data or {}
    name, address = _address_fields(billing)
    guid, muid, sid = sc._gen_fingerprint()
    stripe_js_id = _ctx_value(checkout_data, "stripe_js_id", "client_session_id") or str(uuid.uuid4())
    elements_session_id = _ctx_value(checkout_data, "elements_session_id") or sc._gen_elements_session_id()
    elements_config_id = _ctx_value(
        checkout_data, "elements_session_config_id", "config_id"
    ) or str(uuid.uuid4())
    runtime = str(
        os.getenv("PAY153_STRIPE_JS_VERSION") or DEFAULT_STRIPE_JS_VERSION
    ).strip()
    methods = _payment_method_types(payment_methods)
    data: dict[str, str] = {
        "payment_method_data[type]": "paypal",
        "payment_method_data[billing_details][name]": name,
        "payment_method_data[billing_details][address][line1]": str(address.get("line1") or ""),
        "payment_method_data[billing_details][address][city]": str(address.get("city") or ""),
        "payment_method_data[billing_details][address][country]": str(address.get("country") or "US").upper(),
        "payment_method_data[billing_details][address][postal_code]": str(address.get("postal_code") or ""),
        "payment_method_data[billing_details][address][state]": str(address.get("state") or ""),
        "payment_method_data[payment_user_agent]": (
            f"stripe.js/{runtime}; stripe-js-v3/{runtime}; payment-element; deferred-intent"
        ),
        "payment_method_data[referrer]": "https://chatgpt.com",
        "payment_method_data[time_on_page]": str(int(os.getenv("PAY153_OAICS_TIME_ON_PAGE", "42000") or 42000)),
        "payment_method_data[client_attribution_metadata][client_session_id]": stripe_js_id,
        "payment_method_data[client_attribution_metadata][merchant_integration_source]": "elements",
        "payment_method_data[client_attribution_metadata][merchant_integration_subtype]": "payment-element",
        "payment_method_data[client_attribution_metadata][merchant_integration_version]": "2021",
        "payment_method_data[client_attribution_metadata][payment_intent_creation_flow]": "deferred",
        "payment_method_data[client_attribution_metadata][payment_method_selection_flow]": "merchant_specified",
        "payment_method_data[client_attribution_metadata][elements_session_id]": elements_session_id,
        "payment_method_data[client_attribution_metadata][elements_session_config_id]": elements_config_id,
        "payment_method_data[client_attribution_metadata][merchant_integration_additional_elements][0]": "expressCheckout",
        "payment_method_data[client_attribution_metadata][merchant_integration_additional_elements][1]": "payment",
        "payment_method_data[client_attribution_metadata][merchant_integration_additional_elements][2]": "address",
        "payment_method_data[guid]": guid,
        "payment_method_data[muid]": muid,
        "payment_method_data[sid]": sid,
        "setup_future_usage": "off_session",
        "set_as_default_payment_method": "false",
        "mandate_data[customer_acceptance][type]": "online",
        "mandate_data[customer_acceptance][online][infer_from_client]": "true",
        "client_context[currency]": str(currency or "eur").lower(),
        "client_context[mode]": "subscription",
        "key": publishable_key,
        # Stripe.js sends the base version as a form field; the beta-enabled
        # version belongs in the request header used by the advanced path.
        "_stripe_version": sc.STRIPE_VERSION_BASE,
    }
    for index, method in enumerate(methods):
        data[f"client_context[payment_method_types][{index}]"] = method
    root_metadata = {
        "client_session_id": stripe_js_id,
        "merchant_integration_source": "elements",
        "merchant_integration_subtype": "payment-element",
        "merchant_integration_version": "2021",
        "payment_intent_creation_flow": "deferred",
        "payment_method_selection_flow": "merchant_specified",
        "elements_session_id": elements_session_id,
        "elements_session_config_id": elements_config_id,
    }
    for key, value in root_metadata.items():
        data[f"client_attribution_metadata[{key}]"] = value
    for index, value in enumerate(("expressCheckout", "payment", "address")):
        data[f"client_attribution_metadata[merchant_integration_additional_elements][{index}]"] = value
    email = str(billing.get("email") or "")
    phone = str(billing.get("phone") or "")
    if email:
        data["payment_method_data[billing_details][email]"] = email
    data["payment_method_data[billing_details][phone]"] = phone
    customer = _ctx_value(checkout_data, "customer", "customer_id")
    if customer:
        data["client_context[customer]"] = customer
    hcaptcha_token = str(
        hcaptcha_token or os.getenv("PAY153_OAICS_HCAPTCHA_TOKEN") or ""
    ).strip()
    if hcaptcha_token:
        data["payment_method_data[radar_options][hcaptcha_token]"] = hcaptcha_token
    return data


def create_confirmation_token(
    http,
    *,
    publishable_key: str,
    session_id: str,
    billing: dict[str, Any],
    currency: str,
    payment_methods: list[str] | None,
    checkout_data: dict[str, Any] | None,
    log: Callable[[str], None],
) -> dict[str, Any]:
    data = build_confirmation_token_data(
        publishable_key=publishable_key,
        session_id=session_id,
        billing=billing,
        currency=currency,
        payment_methods=payment_methods,
        checkout_data=checkout_data,
    )
    log(
        "[oaics] 本地接口 confirmation_tokens："
        f"paypal；currency={str(currency or '').lower()}；"
        f"hcaptcha={'已携带' if 'payment_method_data[radar_options][hcaptcha_token]' in data else '未携带'}"
    )
    response = http.post(
        STRIPE_CONFIRMATION_TOKENS_URL,
        data=data,
        headers={
            **sc._stripe_headers(),
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Bearer {publishable_key}",
            # The confirmation_tokens form already carries `_stripe_version`.
            # Stripe rejects the request when the version is duplicated in
            # the Stripe-Version header as well.
        },
        timeout=45,
    )
    payload = _payload(response)
    if getattr(response, "status_code", 0) != 200:
        error = payload.get("error") if isinstance(payload, dict) else {}
        message = error.get("message") if isinstance(error, dict) else ""
        raise OaicsApiError(
            f"confirmation_tokens HTTP {getattr(response, 'status_code', '?')}: "
            f"{message or (getattr(response, 'text', '') or '')[:240]}"
        )
    token_id = str(payload.get("id") or "")
    if not token_id.startswith("ctoken_"):
        raise OaicsApiError("confirmation_tokens 返回缺少 ctoken_*")
    log(f"[oaics] 本地接口 confirmation_tokens 成功：{token_id[:12]}***")
    return {"confirmation_token": token_id, "payload": payload}


def _confirm_headers(
    *,
    checkout_url: str,
    device_id: str,
    language: str,
    sentinel_headers: dict[str, str] | None,
    access_token: str = "",
    country: str = "",
    oai_session_id: str = "",
) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Origin": "https://chatgpt.com",
        **oaics_context_headers(
            country=country,
            device_id=device_id,
            oai_session_id=oai_session_id,
            referer=checkout_url,
            language=language,
        ),
        "x-openai-target-path": "/backend-api/payments/checkout/confirm",
        "x-openai-target-route": "/backend-api/payments/checkout/confirm",
    }
    if access_token and os.getenv(
        "PAY153_OAICS_CONFIRM_AUTH", "1"
    ).strip().lower() not in {"0", "false", "off"}:
        headers["Authorization"] = f"Bearer {access_token}"
    headers.update(sentinel_headers or {})
    return headers


def confirm_oaics_checkout(
    http,
    *,
    session_id: str,
    confirmation_token: str,
    checkout_url: str,
    device_id: str,
    language: str,
    sentinel_headers: dict[str, str] | None,
    access_token: str = "",
    country: str = "",
    oai_session_id: str = "",
    log: Callable[[str], None],
) -> dict[str, Any]:
    if not sentinel_headers:
        raise OaicsApiError("OAICS checkout/confirm 缺少 Sentinel header")
    body = {
        "checkout_session_id": session_id,
        "confirm_token": confirmation_token,
        "selected_payment_method_type": "paypal",
    }
    response = http.post(
        OAICS_CONFIRM_URL,
        json=body,
        headers=_confirm_headers(
            checkout_url=checkout_url,
            device_id=device_id,
            language=language,
            sentinel_headers=sentinel_headers,
            access_token=access_token,
            country=country,
            oai_session_id=oai_session_id,
        ),
        allow_redirects=False,
        timeout=45,
    )
    payload = _payload(response)
    location = str((getattr(response, "headers", {}) or {}).get("location") or "")
    ba_url = extract_paypal_ba_url(payload) or extract_paypal_ba_url(location)
    status = str(payload.get("status") or payload.get("result") or "").lower()
    log(
        f"[oaics] 本地接口 checkout/confirm：HTTP {getattr(response, 'status_code', '?')}；"
        f"status={status or '未暴露'}"
    )
    result = {
        "confirm_payload": payload,
        "client_secret": _find_string(
            payload, ("client_secret", "clientSecret"), prefixes=("pi_", "seti_")
        ),
        "intent_type": _find_string(payload, ("type", "intent_type", "intentType")),
        "confirm_return_url": _find_string(
            payload, ("confirm_return_url", "confirmReturnUrl", "return_url")
        ),
        "confirm_status": status,
        "confirm_http_status": getattr(response, "status_code", None),
        "confirm_location": location,
        "ba_url": ba_url,
    }
    if ba_url:
        return {
            **result,
            "status": "ba_found",
        }
    if status == "blocked":
        return {
            **result,
            "status": "blocked",
            "error": "checkout/confirm 返回 blocked",
        }
    if getattr(response, "status_code", 0) >= 400:
        return {
            **result,
            "status": "confirm_http_error",
            "error": f"checkout/confirm HTTP {getattr(response, 'status_code', '?')}",
        }
    return {
        **result,
        "status": "confirm_without_ba",
        "error": "checkout/confirm 已返回，但响应中没有 PayPal BA 链接",
    }


def fetch_oaics_checkout_state(
    http,
    *,
    access_token: str,
    session_id: str,
    processor_entity: str,
    country: str,
    device_id: str,
    oai_session_id: str,
    checkout_url: str,
    language: str = "",
    log: Callable[[str], None] = lambda _message: None,
) -> dict[str, Any]:
    route = f"/backend-api/payments/checkout/{processor_entity}/{session_id}"
    response = http.get(
        f"{OAICS_CHECKOUT_BASE}/{processor_entity}/{session_id}",
        headers=_oaics_headers(
            access_token=access_token,
            country=country,
            device_id=device_id,
            oai_session_id=oai_session_id,
            referer=checkout_url,
            language=language,
            route=route,
        ),
        timeout=45,
    )
    status = getattr(response, "status_code", 0)
    if status != 200:
        raise OaicsApiError(
            f"读取 OAICS Checkout HTTP {status}: {_response_detail(response)}"
        )
    payload = _payload(response)
    log(
        "[oaics] checkout state：HTTP 200；"
        f"publishable_key={'存在' if resolve_publishable_key(payload) else '缺失'}；"
        f"customer_session_client_secret={'存在' if _find_string(payload, ('customer_session_client_secret', 'customerSessionClientSecret')) else '缺失'}；"
        f"methods={oaics_payment_method_types(payload) or ['未暴露']}"
    )
    return payload


def submit_oaics_checkout_taxes(
    http,
    *,
    access_token: str,
    session_id: str,
    processor_entity: str,
    billing: dict[str, Any],
    country: str,
    currency: str,
    device_id: str,
    oai_session_id: str,
    checkout_url: str,
    language: str = "",
    log: Callable[[str], None] = lambda _message: None,
) -> dict[str, Any]:
    address = billing.get("address") if isinstance(billing, dict) else {}
    address = address if isinstance(address, dict) else {}
    billing_country = str(
        address.get("country") or billing.get("country") or country or ""
    ).upper()
    body = {
        "checkout_session_id": session_id,
        "checkout_email": str(billing.get("email") or ""),
        "billing_country": billing_country,
        "billing_name": str(billing.get("name") or ""),
        "currency": str(currency or "").upper(),
        "tax_id": str(billing.get("tax_id") or "") or None,
        "processor_entity": processor_entity,
        "billing_address": {
            "country": billing_country,
            "line1": str(address.get("line1") or ""),
            "line2": str(address.get("line2") or ""),
            "city": str(address.get("city") or ""),
            "state": str(address.get("state") or ""),
            "postal_code": str(address.get("postal_code") or ""),
        },
    }
    response = http.post(
        OAICS_TAXES_URL,
        json=body,
        headers={
            **_oaics_headers(
                access_token=access_token,
                country=country,
                device_id=device_id,
                oai_session_id=oai_session_id,
                referer=checkout_url,
                language=language,
                route="/backend-api/payments/checkout/taxes",
            ),
            "Content-Type": "application/json",
        },
        timeout=50,
    )
    status = getattr(response, "status_code", 0)
    if status != 200:
        raise OaicsApiError(
            f"提交 OAICS 账单税区 HTTP {status}: {_response_detail(response)}"
        )
    payload = _payload(response)
    observations = oaics_amount_observations(payload)
    log(
        "[oaics] checkout/taxes：HTTP 200；"
        f"billing={billing_country}/{str(currency or '').upper()}；"
        f"amount={observations[0][1] if observations else '未暴露'}"
    )
    return payload


def create_oaics_elements_session(
    http,
    *,
    checkout_data: dict[str, Any],
    country: str,
    currency: str,
    payment_methods: list[str] | None,
    log: Callable[[str], None] = lambda _message: None,
) -> dict[str, Any]:
    publishable_key = resolve_publishable_key(checkout_data)
    customer_secret = _find_string(
        checkout_data,
        ("customer_session_client_secret", "customerSessionClientSecret"),
    )
    if not publishable_key:
        raise OaicsApiError("OAICS PayPal 缺少 Stripe publishable_key")
    if not customer_secret:
        raise OaicsApiError("OAICS PayPal 缺少 customer_session_client_secret")
    methods = [str(item).lower() for item in (payment_methods or []) if str(item).strip()]
    if not methods:
        methods = oaics_payment_method_types(checkout_data)
    if "paypal" not in methods:
        raise OaicsApiError(
            f"OAICS Checkout 当前未暴露 PayPal，可用方式：{', '.join(methods) or '未知'}"
        )
    observations = oaics_amount_observations(checkout_data)
    amount = observations[0][1] if observations else 0
    stripe_js_id = _ctx_value(checkout_data, "stripe_js_id", "client_session_id") or str(uuid.uuid4())
    locale = str(
        (getattr(sc, "_profile", lambda _country: {})(country) or {}).get(
            "browser_locale"
        )
        or "en-US"
    )
    params: dict[str, str] = {
        "customer_session_client_secret": customer_secret,
        "client_betas[0]": "custom_checkout_server_updates_1",
        "client_betas[1]": "custom_checkout_manual_approval_1",
        "deferred_intent[mode]": "subscription",
        "deferred_intent[amount]": str(amount),
        "deferred_intent[currency]": str(currency or "").lower(),
        "deferred_intent[setup_future_usage]": "off_session",
        "currency": str(currency or "").lower(),
        "key": publishable_key,
        "_stripe_version": getattr(sc, "STRIPE_VERSION_FULL", sc.STRIPE_VERSION_BASE),
        "elements_init_source": "stripe.elements",
        "referrer_host": "chatgpt.com",
        "stripe_js_id": stripe_js_id,
        "locale": locale,
        "type": "deferred_intent",
    }
    for index, method in enumerate(methods):
        params[f"deferred_intent[payment_method_types][{index}]"] = method
    response = http.get(
        STRIPE_ELEMENTS_SESSIONS_URL,
        params=params,
        # Stripe rejects this request when the API version is supplied both
        # as `_stripe_version` and as the `Stripe-Version` header.  The
        # Elements protocol uses the query parameter, matching stripe.js and
        # the known-good link-pp implementation.
        headers=sc._stripe_headers(),
        timeout=45,
    )
    status = getattr(response, "status_code", 0)
    if status != 200:
        raise OaicsApiError(
            f"OAICS PayPal Elements Session HTTP {status}: {_response_detail(response)}"
        )
    payload = _payload(response)
    payload["_oaics_publishable_key"] = publishable_key
    payload["_oaics_stripe_js_id"] = stripe_js_id
    payload["_oaics_payment_method_types"] = methods
    log(
        "[oaics] Stripe Elements Session：HTTP 200；"
        f"methods={methods}；session={'存在' if _find_string(payload, ('session_id', 'sessionId', 'id')) else '缺失'}；"
        f"config={'存在' if _find_string(payload, ('config_id', 'elements_session_config_id', 'elementsSessionConfigId')) else '缺失'}"
    )
    return payload


def confirm_oaics_paypal_intent(
    http,
    *,
    confirmation_token: str,
    app_confirm: dict[str, Any],
    elements: dict[str, Any],
    log: Callable[[str], None] = lambda _message: None,
) -> dict[str, Any]:
    publishable_key = str(elements.get("_oaics_publishable_key") or "").strip()
    client_secret = str(
        app_confirm.get("client_secret")
        or _find_string(app_confirm, ("client_secret", "clientSecret"))
        or ""
    ).strip()
    if "_secret_" not in client_secret:
        raise OaicsApiError("OAICS checkout/confirm 未返回 Intent client_secret")
    intent_id = client_secret.split("_secret_", 1)[0]
    if intent_id.startswith("pi_"):
        collection, expected_type = "payment_intents", "payment_intent"
    elif intent_id.startswith("seti_"):
        collection, expected_type = "setup_intents", "setup_intent"
    else:
        raise OaicsApiError("OAICS checkout/confirm 返回了未知 Intent")
    intent_type = str(
        app_confirm.get("intent_type")
        or _find_string(app_confirm, ("type", "intent_type", "intentType"))
        or ""
    ).lower()
    if intent_type and intent_type != expected_type:
        raise OaicsApiError("OAICS checkout/confirm 返回的 Intent 类型不一致")
    body: dict[str, str] = {
        "confirmation_token": confirmation_token,
        "client_secret": client_secret,
        "use_stripe_sdk": "true",
        "key": publishable_key,
    }
    return_url = str(
        app_confirm.get("confirm_return_url")
        or _find_string(app_confirm, ("confirm_return_url", "confirmReturnUrl", "return_url"))
        or ""
    ).strip()
    if return_url:
        body["return_url"] = return_url
    route = f"/v1/{collection}/{intent_id}/confirm"
    response = http.post(
        f"{sc.STRIPE_API}{route}",
        data=body,
        headers={
            **sc._stripe_headers(),
            "Authorization": f"Bearer {publishable_key}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Stripe-Version": getattr(sc, "STRIPE_VERSION_FULL", sc.STRIPE_VERSION_BASE),
        },
        timeout=50,
    )
    status = getattr(response, "status_code", 0)
    payload = _payload(response)
    log(
        f"[oaics] Stripe {collection}/{intent_id[:16]} confirm：HTTP {status}"
    )
    if status != 200:
        raise OaicsApiError(
            f"OAICS PayPal Intent confirm HTTP {status}: {_response_detail(response)}"
        )
    return payload


def extract_oaics_redirect(value: Any) -> str:
    """提取 BA 或 Stripe 的中间 PayPal 跳转地址。"""
    ba_url = extract_paypal_ba_url(value)
    if ba_url:
        return ba_url
    for item in _strings(value):
        text = _normalize_url(item)
        match = _PM_REDIRECT_RE.search(text)
        if match:
            return text[match.start() : match.end()].rstrip(".,)")
    return ""


def resolve_oaics_paypal_redirect(http, value: Any, log: Callable[[str], None]) -> str:
    candidate = extract_oaics_redirect(value)
    if not candidate:
        return ""
    if validate_paypal_ba_url(candidate):
        return candidate
    parsed = urlsplit(candidate)
    if (parsed.hostname or "").lower() != "pm-redirects.stripe.com":
        return ""
    current = candidate
    for attempt in range(1, 5):
        response = http.get(
            current,
            headers={**sc._stripe_headers(), "Accept": "text/html,application/xhtml+xml"},
            allow_redirects=False,
            timeout=45,
        )
        location = ""
        for key, value in (getattr(response, "headers", {}) or {}).items():
            if str(key).lower() == "location":
                location = str(value or "")
                break
        next_url = extract_oaics_redirect(location) or extract_oaics_redirect(_payload(response))
        if not next_url:
            next_url = extract_oaics_redirect(getattr(response, "text", "") or "")
        log(f"[oaics] PayPal 中间跳转解析 {attempt}/4：HTTP {getattr(response, 'status_code', '?')}")
        if not next_url:
            return ""
        if validate_paypal_ba_url(next_url):
            return next_url
        next_host = (urlsplit(next_url).hostname or "").lower()
        if next_host != "pm-redirects.stripe.com":
            return ""
        current = next_url
    return ""


def run_oaics_paypal_api_confirmation(
    *,
    http,
    checkout_data: dict[str, Any],
    checkout_url: str,
    session_id: str,
    billing: dict[str, Any],
    currency: str,
    payment_methods: list[str] | None,
    device_id: str,
    language: str,
    sentinel_headers: dict[str, str] | None,
    access_token: str = "",
    processor_entity: str = "",
    country: str = "",
    oai_session_id: str = "",
    require_zero: bool = False,
    sentinel_headers_factory: Callable[[], dict[str, str]] | None = None,
    log: Callable[[str], None] = lambda _message: None,
) -> dict[str, Any]:
    """完整执行本地 OAICS PayPal 接口链。

    为了兼容早期调用方，当未提供 ``processor_entity`` 且 Checkout 也没有
    ``customer_session_client_secret`` 时保留旧的两步协议；真正的 OAICS
    调用会自动进入 state → taxes → Elements → ctoken → confirm → Intent
    分支。
    """
    token_created = False
    request_country = str(
        country
        or ((billing.get("address") or {}).get("country") if isinstance(billing, dict) else "")
        or "US"
    ).upper()
    current_oai_session_id = str(oai_session_id or uuid.uuid4())
    advanced = bool(
        processor_entity
        or _find_string(
            checkout_data,
            ("customer_session_client_secret", "customerSessionClientSecret"),
        )
    )
    try:
        publishable_key = resolve_publishable_key(checkout_data)
        if not publishable_key and not advanced:
            return {
                "status": "publishable_key_missing",
                "error": "OAICS Checkout 未返回 publishable_key，无法调用 Stripe confirmation_tokens",
                "ba_url": "",
                "confirmation_token_present": False,
                "confirm_status": "",
            }
        effective_data = dict(checkout_data)
        elements: dict[str, Any] = {}
        if advanced:
            if not processor_entity:
                processor_entity = str(
                    checkout_data.get("processor_entity")
                    or checkout_data.get("processor")
                    or ""
                ).strip()
            if not processor_entity:
                raise OaicsApiError("OAICS Checkout 缺少 processor_entity")
            effective_checkout_url = checkout_url or (
                f"https://chatgpt.com/checkout/{processor_entity}/{session_id}"
            )
            state: dict[str, Any] = {}
            try:
                state = fetch_oaics_checkout_state(
                    http,
                    access_token=access_token,
                    session_id=session_id,
                    processor_entity=processor_entity,
                    country=request_country,
                    device_id=device_id,
                    oai_session_id=current_oai_session_id,
                    checkout_url=effective_checkout_url,
                    language=language,
                    log=log,
                )
            except OaicsApiError as exc:
                # Some deployments do not expose a second state read after the
                # create response.  Keep the create snapshot for non-auth
                # errors; a 401 must still stop the attempt.
                if "HTTP 401" in str(exc):
                    raise
                log(f"[oaics] checkout state 读取提示：{str(exc)[:180]}；继续使用创建响应")
            taxes = submit_oaics_checkout_taxes(
                http,
                access_token=access_token,
                session_id=session_id,
                processor_entity=processor_entity,
                billing=billing,
                country=request_country,
                currency=currency,
                device_id=device_id,
                oai_session_id=current_oai_session_id,
                checkout_url=effective_checkout_url,
                language=language,
                log=log,
            )
            effective_data = _merge_payloads(checkout_data, state, taxes)
            publishable_key = resolve_publishable_key(effective_data)
            if not publishable_key:
                raise OaicsApiError(
                    "OAICS Checkout 未返回 publishable_key，无法调用 Stripe confirmation_tokens"
                )
            methods = [str(item).lower() for item in (payment_methods or []) if str(item).strip()]
            if not methods:
                methods = oaics_payment_method_types(effective_data)
            if "paypal" not in methods:
                return {
                    "status": "payment_method_unavailable",
                    "error": f"当前支付线路未开放 PayPal，可用方式：{', '.join(methods) or '未知'}",
                    "ba_url": "",
                    "confirmation_token_present": False,
                    "confirm_status": "",
                }
            amount_payload = {"checkout": checkout_data, "state": state, "taxes": taxes}
            observations = oaics_amount_observations(amount_payload)
            if require_zero:
                verify_oaics_zero_snapshot(amount_payload, currency=currency)
                log("[oaics] 原生优惠金额校验通过：应付 amount=0")
            else:
                log(
                    "[oaics] 账单金额观察："
                    + (", ".join(f"{label}={amount}" for label, amount in observations[:6]) or "未暴露")
                )
            elements = create_oaics_elements_session(
                http,
                checkout_data=effective_data,
                country=request_country,
                currency=currency,
                payment_methods=methods,
                log=log,
            )
            element_session_id = _find_string(
                elements, ("session_id", "sessionId", "id"), prefixes=("elements_session_",)
            )
            element_config_id = _find_string(
                elements,
                ("config_id", "elements_session_config_id", "elementsSessionConfigId"),
            )
            element_customer = _find_string(
                elements, ("customer", "customer_id", "customerId"), prefixes=("cus_",)
            )
            effective_data = _merge_payloads(
                effective_data,
                {
                    "elements_session_id": element_session_id,
                    "elements_session_config_id": element_config_id,
                    "customer": element_customer,
                    "stripe_js_id": elements.get("_oaics_stripe_js_id") or "",
                },
            )
            payment_methods = methods
            checkout_url = effective_checkout_url
        token_result = create_confirmation_token(
            http,
            publishable_key=publishable_key,
            session_id=session_id,
            billing=billing,
            currency=currency,
            payment_methods=payment_methods,
            checkout_data=effective_data,
            log=log,
        )
        confirmation_token = str(token_result["confirmation_token"])
        token_created = True
        confirm_result = confirm_oaics_checkout(
            http,
            session_id=session_id,
            confirmation_token=confirmation_token,
            checkout_url=checkout_url,
            device_id=device_id,
            language=language,
            sentinel_headers=sentinel_headers,
            access_token=access_token,
            country=request_country,
            oai_session_id=current_oai_session_id,
            log=log,
        )
        # A blocked result can be caused by a stale Sentinel proof.  Reuse the
        # same confirmation token once with a freshly generated proof when the
        # caller can provide one; the outer task retry remains the fallback.
        if (
            advanced
            and confirm_result.get("status") == "blocked"
            and sentinel_headers_factory is not None
        ):
            log("[oaics] checkout/confirm 首次 blocked，刷新 Sentinel 后重试同一 token")
            refreshed = sentinel_headers_factory()
            if refreshed:
                confirm_result = confirm_oaics_checkout(
                    http,
                    session_id=session_id,
                    confirmation_token=confirmation_token,
                    checkout_url=checkout_url,
                    device_id=device_id,
                    language=language,
                    sentinel_headers=refreshed,
                    access_token=access_token,
                    country=request_country,
                    oai_session_id=current_oai_session_id,
                    log=log,
                )
        confirm_result["confirmation_token_present"] = True
        if (
            advanced
            and not confirm_result.get("ba_url")
            and confirm_result.get("status") not in {"blocked", "confirm_http_error"}
        ):
            redirect = resolve_oaics_paypal_redirect(
                http,
                {
                    "confirm_payload": confirm_result.get("confirm_payload") or {},
                    "location": confirm_result.get("confirm_location") or "",
                },
                log,
            )
            if redirect:
                confirm_result["status"] = "ba_found"
                confirm_result["ba_url"] = redirect
                confirm_result["intent_confirmed"] = False
                confirm_result.pop("error", None)
        if (
            advanced
            and not confirm_result.get("ba_url")
            and confirm_result.get("status") not in {"blocked", "confirm_http_error"}
            and confirm_result.get("client_secret")
        ):
            intent_result = confirm_oaics_paypal_intent(
                http,
                confirmation_token=confirmation_token,
                app_confirm=confirm_result,
                elements=elements,
                log=log,
            )
            confirm_result["intent_confirm_payload"] = intent_result
            redirect = resolve_oaics_paypal_redirect(http, intent_result, log)
            if redirect:
                confirm_result["status"] = "ba_found"
                confirm_result["ba_url"] = redirect
                confirm_result["intent_confirmed"] = True
                confirm_result.pop("error", None)
            else:
                confirm_result["status"] = "intent_without_ba"
                confirm_result["error"] = "Stripe Intent confirm 已返回，但没有 PayPal BA 跳转"
        return confirm_result
    except OaicsApiError as exc:
        return {
            "status": "api_error",
            "error": str(exc),
            "ba_url": "",
            "confirmation_token_present": token_created,
            "confirm_status": "",
        }
