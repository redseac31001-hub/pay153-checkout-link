"""一次性：随机抽检 Manage 代理池，对比 双层PRE / 直连池 / 本机基线。"""
from __future__ import annotations

import os
import random
import sys
import time
import traceback
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# 加载 .env（与运行时一致）
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())

import stripe_checkout as sc  # noqa: E402
from manage_store import ManageStore  # noqa: E402


def mask_proxy(proxy: str) -> str:
    text = str(proxy or "").strip()
    if not text:
        return ""
    try:
        parsed = urlsplit(text if "://" in text else f"socks5h://{text}")
        host = parsed.hostname or "?"
        port = parsed.port or ""
        user = parsed.username or ""
        scheme = parsed.scheme or ""
        if user:
            return f"{scheme}://{user[:2]}***@{host}:{port}"
        return f"{scheme}://{host}:{port}"
    except Exception:
        return text[:32] + "..."


def classify(message: str) -> str:
    low = str(message or "").lower()
    if "proxy" in low:
        return "PROXY_CHAIN"
    if "ssl" in low:
        return "SSL"
    if "timeout" in low or "timed out" in low:
        return "TIMEOUT"
    if "connect" in low:
        return "CONNECT"
    if "curl" in low:
        return "CURL"
    return "OTHER"


def try_geo(label: str, proxy: str | None = None, force_pre=None, timeout: int = 15) -> dict:
    """force_pre: None=线上一致 build_http; False=关PRE; str=指定PRE。"""
    from curl_cffi.const import CurlOpt
    from curl_cffi.requests import Session

    started = time.time()
    try:
        if force_pre is False:
            http = Session(impersonate="chrome136", curl_options={})
            if proxy:
                http.proxies = {"http": proxy, "https": proxy}
        elif isinstance(force_pre, str):
            http = Session(
                impersonate="chrome136",
                curl_options={CurlOpt.PRE_PROXY: force_pre},
            )
            if proxy:
                http.proxies = {"http": proxy, "https": proxy}
        else:
            http = sc.build_http(proxy)

        probes = (
            "http://ip-api.com/json/?fields=status,countryCode,regionName,city,query",
            "https://ipapi.co/json/",
            "https://api.ipify.org?format=json",
        )
        errors: list[str] = []
        for url in probes:
            try:
                response = http.get(url, timeout=timeout)
                if getattr(response, "status_code", 0) != 200:
                    errors.append(f"{url} HTTP {getattr(response, 'status_code', 0)}")
                    continue
                try:
                    data = response.json() or {}
                except Exception:
                    errors.append(f"{url} bad-json")
                    continue
                ip = str(data.get("ip") or data.get("query") or "").strip()
                country = str(
                    data.get("countryCode")
                    or data.get("country_code")
                    or data.get("country")
                    or ""
                ).strip()
                if len(country) != 2:
                    country = str(data.get("country_code") or data.get("countryCode") or "").upper()
                else:
                    country = country.upper()
                region = str(data.get("regionName") or data.get("region") or "")
                city = str(data.get("city") or "")
                if not ip and not country:
                    errors.append(f"{url} empty identity")
                    continue
                return {
                    "ok": True,
                    "label": label,
                    "ms": int((time.time() - started) * 1000),
                    "ip": ip,
                    "country": country,
                    "region": region,
                    "city": city,
                    "via": url,
                    "proxy": mask_proxy(proxy or ""),
                }
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{url} {type(exc).__name__}:{str(exc)[:100]}")
        joined = " | ".join(errors[-3:]) or "no response"
        return {
            "ok": False,
            "label": label,
            "ms": int((time.time() - started) * 1000),
            "error": joined,
            "class": classify(joined),
            "proxy": mask_proxy(proxy or ""),
        }
    except Exception as exc:  # noqa: BLE001
        message = f"{type(exc).__name__}: {exc}"
        return {
            "ok": False,
            "label": label,
            "ms": int((time.time() - started) * 1000),
            "error": message,
            "class": classify(message),
            "proxy": mask_proxy(proxy or ""),
        }


def main() -> int:
    print("=" * 72)
    print("Pay153 代理随机检测诊断")
    print("时间:", time.strftime("%Y-%m-%d %H:%M:%S"))
    print("PRE_PROXY env:", repr(os.getenv("PAY153_PROXY_PRE_PROXY")))
    print("proxy_pre_proxy():", repr(sc.proxy_pre_proxy()))
    print("=" * 72)

    print("\n[A] 基线（不经代理池）")
    baselines = [
        ("A1 本机直连", dict(proxy=None, force_pre=False)),
        ("A2 仅本地9697作主代理", dict(proxy="socks5h://127.0.0.1:9697", force_pre=False)),
        ("A3 仅 PRE_PROXY=9697 无池", dict(proxy=None, force_pre="socks5h://127.0.0.1:9697")),
    ]
    for label, kwargs in baselines:
        result = try_geo(label, **kwargs)
        if result["ok"]:
            print(
                f"  OK  {label}: {result.get('country')}/{result.get('region')}/{result.get('city')} "
                f"ip={result.get('ip')} {result['ms']}ms via={result.get('via')}"
            )
        else:
            print(f"  FAIL {label}: [{result.get('class')}] {result.get('error')} {result['ms']}ms")

    print("\n[B] 读取 Manage 代理池")
    key_file = Path(os.getenv("PAY153_MANAGE_KEY_FILE", "data/.manage.key"))
    db_path = Path(os.getenv("PAY153_MANAGE_DB", "data/pay153_manage.sqlite3"))
    if not key_file.exists():
        print("缺少 data/.manage.key，无法解密代理池")
        return 2
    encryption_key = key_file.read_bytes().strip()
    store = ManageStore(db_path=db_path, encryption_key=encryption_key)
    listed = store.list_proxy_pools()
    print(f"池数量: {len(listed)}")
    pools: list[dict] = []
    for meta in listed:
        full = store.get_proxy_pool(int(meta["id"]), reveal=True)
        proxies = full.get("proxies") or []
        item = {
            "id": meta["id"],
            "name": meta.get("name"),
            "rail": meta.get("rail"),
            "country": meta.get("country"),
            "pool_kind": meta.get("pool_kind"),
            "enabled": meta.get("enabled"),
            "count": len(proxies),
            "proxies": proxies,
            "preview": full.get("proxy_preview") or meta.get("proxy_preview"),
        }
        pools.append(item)
        print(
            f"  #{item['id']} name={item['name']} rail={item['rail']} country={item['country']} "
            f"kind={item['pool_kind']} enabled={item['enabled']} n={item['count']} preview={item['preview']}"
        )

    if not any(pool["proxies"] for pool in pools):
        print("没有可解密的代理条目")
        return 3

    print("\n[C] 随机抽检（每池最多 3 条；对比 双层PRE / 直连池）")
    rng = random.SystemRandom()
    summary: list[dict] = []
    for pool in pools:
        proxies = list(pool["proxies"] or [])
        if not proxies:
            print(f"\n-- 池#{pool['id']} {pool['name']} 空，跳过")
            continue
        sample = proxies if len(proxies) <= 3 else rng.sample(proxies, 3)
        print(
            f"\n-- 池#{pool['id']} {pool['name']} rail={pool['rail']} country={pool['country']} "
            f"kind={pool['pool_kind']} 抽样 {len(sample)}/{len(proxies)}"
        )
        for index, proxy in enumerate(sample, 1):
            print(f"  样本{index}: {mask_proxy(proxy)}")
            dual = try_geo("双层PRE+池", proxy=proxy, force_pre=None)
            direct = try_geo("直连池无PRE", proxy=proxy, force_pre=False)
            for result in (dual, direct):
                if result["ok"]:
                    print(
                        f"    OK  {result['label']}: {result.get('country')}/{result.get('region')}/"
                        f"{result.get('city')} ip={result.get('ip')} {result['ms']}ms"
                    )
                else:
                    print(
                        f"    FAIL {result['label']}: [{result.get('class')}] "
                        f"{result.get('error')} {result['ms']}ms"
                    )
                summary.append(
                    {
                        **result,
                        "pool_id": pool["id"],
                        "pool_name": pool["name"],
                        "pool_kind": pool["pool_kind"],
                        "rail": pool["rail"],
                    }
                )

    print("\n[D] 使用 app.proxy_geo / probe_proxy_identity（与提链/随机检测相同）")
    try:
        import app as app_module  # noqa: WPS433

        pairs: list[tuple[dict, str]] = []
        for pool in pools:
            for proxy in pool["proxies"]:
                pairs.append((pool, proxy))
        sample_pairs = pairs if len(pairs) <= 5 else rng.sample(pairs, 5)
        for pool, proxy in sample_pairs:
            print(f"  抽检 pool#{pool['id']} {pool['name']} {mask_proxy(proxy)}")
            started = time.time()
            try:
                geo = app_module.proxy_geo(proxy)
                print(
                    f"    proxy_geo OK: country={geo.get('country')} region={geo.get('region')} "
                    f"city={geo.get('city')} ip={geo.get('ip')} {int((time.time() - started) * 1000)}ms"
                )
            except Exception as exc:  # noqa: BLE001
                print(
                    f"    proxy_geo FAIL: {type(exc).__name__}: {exc} "
                    f"{int((time.time() - started) * 1000)}ms"
                )
            started = time.time()
            try:
                identity = app_module.probe_proxy_identity(proxy)
                print(
                    f"    probe_proxy_identity OK: {identity} "
                    f"{int((time.time() - started) * 1000)}ms"
                )
            except Exception as exc:  # noqa: BLE001
                print(
                    f"    probe_proxy_identity FAIL: {type(exc).__name__}: {exc} "
                    f"{int((time.time() - started) * 1000)}ms"
                )
    except Exception:
        traceback.print_exc()

    print("\n[E] 汇总")
    ok_pre = sum(1 for item in summary if item.get("label") == "双层PRE+池" and item.get("ok"))
    fail_pre = sum(1 for item in summary if item.get("label") == "双层PRE+池" and not item.get("ok"))
    ok_direct = sum(1 for item in summary if item.get("label") == "直连池无PRE" and item.get("ok"))
    fail_direct = sum(1 for item in summary if item.get("label") == "直连池无PRE" and not item.get("ok"))
    print(f"双层 PRE+池: OK {ok_pre} / FAIL {fail_pre}")
    print(f"直连池无PRE: OK {ok_direct} / FAIL {fail_direct}")
    classes = Counter(item.get("class") for item in summary if not item.get("ok"))
    print("失败分类:", dict(classes))
    if fail_pre and ok_direct:
        print("判断: 池本身可能可达，问题更像双层 PRE_PROXY 链路（9697→池）")
    elif fail_pre and fail_direct:
        print("判断: 池条目本身大面积不可达（凭据/节点/协议），不只是本地代理问题")
    elif ok_pre:
        print("判断: 抽样双层可用；任务失败更可能是抽到坏节点或间歇性故障")
    else:
        print("判断: 需结合明细")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
