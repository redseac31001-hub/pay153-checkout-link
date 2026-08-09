"""
测试不同 Stripe API 版本对 PayPal 支持的影响

用于诊断为什么 payment_method_types 不包含 paypal
"""

import stripe_checkout as sc
import os
import sys

def test_api_version(session_id: str, proxy: str, api_version: str, test_name: str):
    """
    测试指定 API 版本是否返回 PayPal 支持

    Args:
        session_id: Stripe checkout session ID (cs_live_xxx)
        proxy: 代理地址
        api_version: Stripe API 版本号
        test_name: 测试名称
    """
    print(f"\n{'='*60}")
    print(f"测试：{test_name}")
    print(f"API 版本：{api_version}")
    print(f"{'='*60}")

    try:
        # 构建 HTTP 客户端
        http = sc.build_http(proxy)

        # 验证 publishable key
        print("[1/3] 正在验证 publishable key...")
        pk = sc.verify_pk(http, session_id, lambda m: print(f"    {m}"))
        print(f"    ✓ pk: {pk[:20]}...")

        # 构建测试 profile
        profile = {
            "browser_locale": "en-US",
            "browser_timezone": "America/New_York",
            "fingerprint": "test",
        }

        # 临时修改 API 版本
        original_version = sc.PAYPAL_STRIPE_VERSION
        sc.PAYPAL_STRIPE_VERSION = api_version

        # 初始化 Checkout
        print(f"[2/3] 正在初始化 Checkout (使用 {api_version})...")
        init_data, version, ctx = sc.init_checkout(
            http, session_id, pk, profile,
            lambda m: print(f"    {m}")
        )

        # 恢复原版本
        sc.PAYPAL_STRIPE_VERSION = original_version

        # 检查结果
        print("[3/3] 检查 payment_method_types...")
        payment_methods = ctx.get("payment_method_types", [])
        amount = ctx.get("checkout_amount", "unknown")
        currency = ctx.get("currency", "unknown")

        print(f"    金额: {amount}")
        print(f"    货币: {currency}")
        print(f"    支付方式: {payment_methods}")

        if "paypal" in payment_methods:
            print(f"    ✅ 成功：PayPal 已开放")
            return True
        else:
            print(f"    ❌ 失败：PayPal 未开放")
            return False

    except Exception as e:
        print(f"    ❌ 错误：{type(e).__name__}: {e}")
        return False


def main():
    print("""
╔═══════════════════════════════════════════════════════════╗
║     Stripe API 版本测试工具                               ║
║     用于诊断 PayPal payment_method_types 问题             ║
╚═══════════════════════════════════════════════════════════╝
""")

    # 从环境变量或命令行参数获取测试参数
    session_id = os.getenv("TEST_SESSION_ID") or (sys.argv[1] if len(sys.argv) > 1 else None)
    proxy = os.getenv("TEST_PROXY") or (sys.argv[2] if len(sys.argv) > 2 else None)

    if not session_id or not proxy:
        print("""
使用方法：

    方法 1：环境变量
    export TEST_SESSION_ID="cs_live_xxxxx"
    export TEST_PROXY="socks5://proxy:port"
    python test_stripe_api_versions.py

    方法 2：命令行参数
    python test_stripe_api_versions.py "cs_live_xxxxx" "socks5://proxy:port"

说明：
    - session_id: 从 OpenAI Checkout API 获取的 Stripe session
    - proxy: 你的代理地址（支持 socks5/http）
        """)
        sys.exit(1)

    print(f"Session ID: {session_id[:30]}...")
    print(f"Proxy: {proxy}")

    # 测试不同的 API 版本
    versions_to_test = [
        {
            "version": "2020-08-27;custom_checkout_beta=v1",
            "name": "2020 旧版本（你当前使用的）",
        },
        {
            "version": "2025-03-31.basil",
            "name": "2025 基础版本（无 beta）",
        },
        {
            "version": "2025-03-31.basil;checkout_server_update_beta=v1;checkout_manual_approval_preview=v1",
            "name": "2025 完整版本（带 beta）",
        },
        {
            "version": "2024-06-03.basil",
            "name": "2024 中期版本",
        },
    ]

    results = {}
    for test in versions_to_test:
        success = test_api_version(
            session_id=session_id,
            proxy=proxy,
            api_version=test["version"],
            test_name=test["name"]
        )
        results[test["name"]] = success

    # 输出总结
    print(f"\n{'='*60}")
    print("测试总结")
    print(f"{'='*60}")

    success_count = sum(results.values())
    total_count = len(results)

    for name, success in results.items():
        status = "✅ 成功" if success else "❌ 失败"
        print(f"{status} - {name}")

    print(f"\n成功率：{success_count}/{total_count}")

    if success_count == 0:
        print("\n⚠️  所有版本都失败了，可能的原因：")
        print("  1. 代理 IP 被 Stripe/PayPal 风控")
        print("  2. Stripe Dashboard 未启用 PayPal")
        print("  3. 账户/地区不支持 PayPal")
        print("  4. 优惠导致金额为 0，Stripe 移除了 PayPal")
    elif success_count < total_count:
        print("\n💡 建议：")
        successful = [name for name, success in results.items() if success]
        print(f"  使用成功的版本：{successful[0]}")
    else:
        print("\n✅ 所有版本都支持 PayPal，问题可能不在 API 版本")

    print("\n" + "="*60)


if __name__ == "__main__":
    main()
