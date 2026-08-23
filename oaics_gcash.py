"""OAICS GCash checkout adapter.

GCash is an OpenAI-managed checkout flow.  It is intentionally kept separate
from the Stripe provider adapter: the payment action is created by OpenAI,
then completed through the Adyen/Mynt redirect contract.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from oaics_api import (
    oaics_context_headers,
    submit_oaics_checkout_taxes,
    verify_oaics_zero_snapshot,
)
import stripe_checkout as sc


CHATGPT_BASE = "https://chatgpt.com"
GCASH_UPDATE = f"{CHATGPT_BASE}/backend-api/payments/checkout/update"
GCASH_CONFIRM = f"{CHATGPT_BASE}/backend-api/payments/checkout/confirm"
GCASH_START = f"{CHATGPT_BASE}/backend-api/payments/checkout/custom_payment_method/start"
GCASH_CONTINUE = f"{CHATGPT_BASE}/backend-api/payments/checkout/custom_payment_method/continue"
MYNT_URL = "https://mgs-gw.paas.mynt.xyz/mgw.htm"


class GcashFlowError(RuntimeError):
    def __init__(self, message: str, *, error_code: str = ""):
        super().__init__(message)
        self.error_code = error_code


def _payload(response) -> dict[str, Any]:
    try:
        value = response.json()
        return value if isinstance(value, dict) else {"data": value}
    except Exception:
        try:
            value = json.loads(response.text or "{}")
            return value if isinstance(value, dict) else {"data": value}
        except Exception:
            return {}


def _headers(token: str, country: str, device_id: str, session_id: str, referer: str, route: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": CHATGPT_BASE,
        **oaics_context_headers(country=country, device_id=device_id, oai_session_id=session_id, referer=referer),
        "x-openai-target-path": route,
        "x-openai-target-route": route,
    }


def _post(http, url: str, body: dict[str, Any], headers: dict[str, str], log, *, allow_redirects: bool = True) -> dict[str, Any]:
    response = http.post(url, json=body, headers=headers, allow_redirects=allow_redirects, timeout=50)
    payload = _payload(response)
    if response.status_code >= 400:
        raise GcashFlowError(f"GCash {url.rsplit('/', 1)[-1]} HTTP {response.status_code}: {(response.text or '')[:300]}")
    return {"payload": payload, "status_code": response.status_code, "headers": dict(response.headers or {}), "location": str((response.headers or {}).get("location") or "")}


def _find(value: Any, names: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        for name in names:
            if value.get(name) not in (None, "", [], {}):
                return value[name]
        for nested in value.values():
            found = _find(nested, names)
            if found not in (None, "", [], {}):
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find(nested, names)
            if found not in (None, "", [], {}):
                return found
    return None


def _gcash_method_id(checkout_data: dict[str, Any]) -> str:
    """Return the server-provided custom payment-method id.

    PayPal is a built-in enum (``paypal``), while GCash is advertised by
    OAICS under ``custom_payment_methods``.  Never invent that opaque id.
    """
    containers: list[Any] = []
    if isinstance(checkout_data, dict):
        containers.extend([checkout_data.get("custom_payment_methods"), checkout_data.get("customPaymentMethods")])
    candidates: list[tuple[str, dict[str, Any]]] = []
    seen_ids: set[str] = set()
    for container in containers:
        values = container if isinstance(container, list) else [container]
        for item in values:
            if not isinstance(item, dict):
                continue
            label = " ".join(str(item.get(key) or "") for key in ("id", "type", "name", "display_name", "label")).lower()
            method_id = str(item.get("id") or "").strip()
            if method_id and method_id not in seen_ids:
                seen_ids.add(method_id)
                candidates.append((label, item))

    # custom_payment_methods IDs are opaque (for example ``cpmt_...``), so
    # the provider name is not necessarily present in the ID.  Prefer an
    # explicitly labelled GCash/Mynt entry, then accept the sole server
    # supplied custom method.  The latter is safe here because this flow is
    # entered only after the caller selected GCash and the checkout response
    # exposes one custom rail.
    for label, item in candidates:
        if any(keyword in label for keyword in ("gcash", "mynt", "adyen")):
            return str(item["id"]).strip()
    if len(candidates) == 1:
        return str(candidates[0][1]["id"]).strip()
    return ""


def _redirect(value: Any) -> str:
    candidate = _find(value, ("redirect_url", "redirectUrl", "action_url", "actionUrl", "url", "location"))
    return str(candidate or "").strip()


def _with_redirect_result(url: str, redirect_result: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["redirectResult"] = redirect_result
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _mynt_body(operation: str, context: dict[str, Any]) -> dict[str, Any]:
    env = context.get("env_info") or {
        "tokenId": str(context.get("token_id") or uuid.uuid4()),
        "osType": "macOS",
        "osVersion": "10.15.7",
        "browserType": "Chrome",
        "browserVersion": str(context.get("browser_version") or "136"),
        "terminalType": "WEB",
    }
    request: dict[str, Any] = {"envInfo": env}
    if operation.endswith("authorisation.stateless.consult"):
        request.update({
            "channel": "aggregator",
            "urlParameters": str(context.get("url_parameters") or ""),
            "originalUrl": str(context.get("original_url") or ""),
            "expireSeconds": 300,
            "bizType": "ACQUIRING",
            "extParams": {},
        })
    elif operation.endswith("short.dynamic.link"):
        request.update({
            "originalUrl": str(context.get("original_url") or "") + "#/",
            "uuid": str(context.get("uuid") or ""),
            "bizType": "ACQUIRING",
            "expireSeconds": 300,
            "extendInfo": {},
            "extParams": {},
        })
    else:
        request.update({"uuid": str(context.get("uuid") or ""), "extParams": {}})
    return {
        "operationType": operation,
        "requestData": json.dumps([request], separators=(",", ":")),
        "version": "2.0",
        "workspaceId": "PROD",
        "appId": "D54528A131559",
        "tenantId": "MYNTPH",
    }


def _mynt_post(http, operation: str, context: dict[str, Any], log) -> dict[str, Any]:
    response = http.post(
        MYNT_URL,
        data=_mynt_body(operation, context),
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": sc.CHROME_UA,
        },
        timeout=50,
    )
    payload = _payload(response)
    if response.status_code >= 400:
        raise GcashFlowError(f"Mynt {operation} HTTP {response.status_code}: {(response.text or '')[:300]}")
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    if isinstance(result, dict) and result.get("success") is False:
        raise GcashFlowError(f"Mynt {operation} 返回失败")
    return {"payload": payload, "result": result if isinstance(result, dict) else {}}


def _redirect_result_from_location(location: str) -> str:
    query = dict(parse_qsl(urlsplit(str(location or "")).query, keep_blank_values=True))
    return str(query.get("redirectResult") or "").strip()


def run_gcash_flow(*, http, token: str, checkout_data: dict[str, Any], session_id: str, checkout_url: str, processor_entity: str, billing: dict[str, Any], device_id: str, oai_session_id: str, sentinel_headers: dict[str, str] | None, log: Callable[[str], None]) -> dict[str, Any]:
    country, currency = "PH", "PHP"
    referer = checkout_url or f"{CHATGPT_BASE}/checkout/{processor_entity}/{session_id}"
    headers = _headers(token, country, device_id, oai_session_id, referer, "/backend-api/payments/checkout/update")
    update_body = {
        "checkout_session_id": session_id,
        "processor_entity": processor_entity,
        # checkout/update validates the internal PlanName enum, not the UI
        # display label.  The initial Checkout payload uses this same value.
        "plan_name": "chatgptplusplan",
        "price_interval": "month",
        "seat_quantity": 1,
        "discount_code": None,
        "promo_campaign": {"promo_campaign_id": "plus-1-month-free", "is_coupon_from_query_param": False},
    }
    update = None
    taxes = None
    zero_error = ""
    # Some OAICS sessions acknowledge checkout/update but keep the original
    # amount until the session is re-synchronised.  Mirror the other provider
    # flows: update -> taxes -> observe, then retry update on the same session.
    for sync_attempt in range(1, 4):
        update = _post(http, GCASH_UPDATE, update_body, headers, log)
        log(f"[gcash] checkout/update 已提交（优惠同步 {sync_attempt}/3），开始提交账单税区")
        taxes = submit_oaics_checkout_taxes(
            http,
            access_token=token,
            session_id=session_id,
            processor_entity=processor_entity,
            billing=billing,
            country=country,
            currency=currency,
            device_id=device_id,
            oai_session_id=oai_session_id,
            checkout_url=referer,
            language="en-PH",
            log=log,
        )
        try:
            verify_oaics_zero_snapshot({"checkout": update["payload"], "taxes": taxes}, currency=currency)
            zero_error = ""
            log("[gcash] checkout/taxes 已提交，确认金额为 0")
            break
        except Exception as exc:
            zero_error = str(exc)
            log(f"[gcash] 优惠同步后金额仍未归零（{sync_attempt}/3）：{zero_error[:240]}")
            if sync_attempt < 3:
                import time
                time.sleep(1.5)
    else:
        raise GcashFlowError(
            f"GCash 优惠未确认归零：{zero_error or '金额仍未归零'}",
            error_code="gcash_promo_not_applied",
        )
    custom_method_id = _gcash_method_id(checkout_data) or _gcash_method_id(update["payload"])
    if not custom_method_id:
        raise GcashFlowError("Checkout 未返回 GCash custom_payment_method id")
    log(f"[gcash] 使用服务端 custom method id={custom_method_id[:12]}***")
    confirm_headers = dict(headers)
    confirm_headers.update(sentinel_headers or {})
    confirm_headers["x-openai-target-path"] = "/backend-api/payments/checkout/confirm"
    confirm_headers["x-openai-target-route"] = "/backend-api/payments/checkout/confirm"
    # OAICS treats a custom payment method ID as the selected payment method
    # type.  Sending ``gcash`` plus a second custom ID field is rejected by
    # checkout/confirm; PayPal's HAR shows the same single-field contract.
    confirm_body = {"checkout_session_id": session_id, "selected_payment_method_type": custom_method_id}
    confirm = _post(http, GCASH_CONFIRM, confirm_body, confirm_headers, log, allow_redirects=False)
    confirm_payload = confirm["payload"]
    if str(_find(confirm_payload, ("status", "result")) or "").lower() in {"blocked", "failed"}:
        raise GcashFlowError("GCash checkout/confirm 被拒绝", error_code="gcash_confirm_rejected")
    start_body = {"checkout_session_id": session_id, "selected_payment_method_type": custom_method_id}
    start_headers = dict(confirm_headers)
    start_headers["x-openai-target-path"] = "/backend-api/payments/checkout/custom_payment_method/start"
    start_headers["x-openai-target-route"] = "/backend-api/payments/checkout/custom_payment_method/start"
    start = _post(http, GCASH_START, start_body, start_headers, log, allow_redirects=False)
    start_payload = start["payload"]
    start_status = str(_find(start_payload, ("status", "state")) or "").lower()
    if start_status and start_status not in {"requires_action", "requiresaction", "pending", "open"}:
        raise GcashFlowError(f"GCash custom_payment_method/start 状态异常：{start_status}")
    redirect_url = _redirect({"payload": start_payload, "location": start["location"]})
    if not redirect_url:
        raise GcashFlowError("GCash custom_payment_method/start 未返回 Adyen 跳转地址")
    log("[gcash] custom_payment_method/start 返回 requires_action")
    adyen = http.get(redirect_url, headers={"Accept": "text/html,application/xhtml+xml", "User-Agent": sc.CHROME_UA}, allow_redirects=False, timeout=50)
    adyen_location = str((adyen.headers or {}).get("location") or "")
    auth_url = adyen_location or redirect_url
    auth_parts = urlsplit(auth_url)
    context = {
        "original_url": auth_url,
        "url_parameters": auth_parts.query,
        "token_id": str(uuid.uuid4()),
        "browser_version": re.search(r"Chrome/(\d+)", sc.CHROME_UA).group(1) if re.search(r"Chrome/(\d+)", sc.CHROME_UA) else "136",
    }
    consult = _mynt_post(http, "ap.mobilewallet.gka.authorisation.stateless.consult", context, log)
    context.update(consult["result"])
    context["uuid"] = str(consult["result"].get("uuid") or "").strip()
    if not context["uuid"]:
        raise GcashFlowError("Mynt consult 未返回 UUID")
    log(f"[gcash] Mynt consult 已获取 UUID={context['uuid'][:12]}***")
    dynamic = _mynt_post(http, "ap.mobilewallet.short.dynamic.link", context, log)
    context.update(dynamic["result"])
    log("[gcash] Mynt dynamic link 已生成，等待 GCash 手机授权")
    poll_limit = 60
    final_mynt: dict[str, Any] = {}
    for attempt in range(poll_limit):
        result = _mynt_post(http, "ap.mobilewallet.gka.query.result", context, log)
        final_mynt = result["result"]
        return_url = str(final_mynt.get("redirectUrl") or final_mynt.get("redirect_url") or "").strip()
        state = str(_find(final_mynt, ("status", "state", "result")) or "").lower()
        if return_url:
            context["return_url"] = return_url
            break
        if state in {"failed", "rejected", "cancelled", "canceled", "expired"}:
            raise GcashFlowError(f"GCash 手机授权失败：{state}")
        import time
        time.sleep(2)
    else:
        raise GcashFlowError("GCash 手机授权轮询超时")
    return_url = str(context.get("return_url") or "").strip()
    if not return_url:
        raise GcashFlowError("GCash 授权完成但 Mynt 未返回 checkoutPaymentReturn URL")
    returned = http.get(return_url, headers={"Accept": "text/html,application/xhtml+xml", "User-Agent": sc.CHROME_UA}, allow_redirects=False, timeout=50)
    returned_location = str((returned.headers or {}).get("location") or "")
    redirect_result = _redirect_result_from_location(returned_location)
    if not redirect_result:
        redirect_result = _redirect_result_from_location(return_url)
    if not redirect_result:
        raise GcashFlowError("Adyen checkoutPaymentReturn 未返回 redirectResult")
    continue_body = {"checkout_session_id": session_id, "action_result": {"redirectResult": redirect_result}}
    continued = _post(http, GCASH_CONTINUE, continue_body, confirm_headers, log)
    log("[gcash] custom_payment_method/continue 已提交")
    return {"provider": "gcash", "provider_redirect_url": auth_url, "checkout_amount": 0, "checkout_currency": currency, "payment_method_types": ["gcash"], "gcash_status": "authorized", "gcash_continue": continued["payload"], "gcash_mynt": final_mynt, "promo_requested": True, "promo_applied": True, "processor_entity": processor_entity}
