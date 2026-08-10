#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gopay 集成测试脚本 - 验证所有模块导入和基本配置"""

import sys
import io

# 修复 Windows 控制台编码问题
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def test_imports():
    """测试所有必要模块是否能正确导入"""
    print("✓ 测试模块导入...")

    try:
        import provider_checkout
        print("  ✓ provider_checkout 导入成功")
    except ImportError as e:
        print(f"  ✗ provider_checkout 导入失败: {e}")
        return False

    try:
        from provider_checkout import stripe_to_provider, PROVIDER_DEFAULTS
        print("  ✓ 通用 stripe_to_provider 函数导入成功")
        print("  ✓ PROVIDER_DEFAULTS 导入成功")
    except ImportError as e:
        print(f"  ✗ 函数导入失败: {e}")
        return False

    try:
        import app
        print("  ✓ app 模块导入成功")
    except Exception as e:
        print(f"  ✗ app 模块导入失败: {e}")
        return False

    return True

def test_provider_defaults():
    """测试 PROVIDER_DEFAULTS 配置"""
    print("\n✓ 测试 PROVIDER_DEFAULTS 配置...")

    from provider_checkout import PROVIDER_DEFAULTS

    if "gopay" not in PROVIDER_DEFAULTS:
        print("  ✗ PROVIDER_DEFAULTS 中缺少 gopay 配置")
        return False

    gopay_config = PROVIDER_DEFAULTS["gopay"]
    print(f"  ✓ gopay 配置: {gopay_config}")

    if gopay_config.get("country") != "ID":
        print(f"  ✗ gopay 国家代码错误: {gopay_config.get('country')}")
        return False

    if gopay_config.get("currency") != "IDR":
        print(f"  ✗ gopay 币种错误: {gopay_config.get('currency')}")
        return False

    print("  ✓ gopay 配置正确")
    return True

def test_gopay_uses_generic_flow():
    """测试 Gopay 复用通用支付流程，不再依赖第三代理池。"""
    print("\n✓ 测试 Gopay 通用双代理池流程...")

    import inspect
    from provider_checkout import stripe_to_provider

    sig = inspect.signature(stripe_to_provider)
    params = list(sig.parameters.keys())

    print(f"  ✓ 函数参数: {params}")

    required_params = ["http", "session_id", "provider", "billing", "country", "apply_promo_callback"]
    for param in required_params:
        if param not in params:
            print(f"  ✗ 缺少必要参数: {param}")
            return False
    if "th_http" in params or "th_proxies" in params:
        print("  ✗ Gopay 仍暴露泰国第三代理池参数")
        return False

    from app import checkout_payload
    payload = checkout_payload({
        "plan": "plus",
        "country": "ID",
        "currency": "IDR",
        "checkout_country": "ID",
        "checkout_currency": "IDR",
        "link_type": "gopay",
        "use_promo": True,
        "promo_campaign": "plus-1-month-free",
    }, {})
    if "promo_campaign" in payload:
        print("  ✗ Gopay 不应在创建 Checkout 时原生携带优惠")
        return False
    print("  ✓ Gopay 通过通用优惠回调更新，未使用第三代理池")

    print("  ✓ 函数签名正确")
    return True

def main():
    """主测试函数"""
    print("=" * 60)
    print("Gopay 集成测试")
    print("=" * 60)

    tests = [
        test_imports,
        test_provider_defaults,
        test_gopay_uses_generic_flow,
    ]

    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"\n✗ 测试异常: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)

    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"通过: {passed}/{total}")

    if all(results):
        print("\n✓ 所有测试通过！Gopay 集成配置正确。")
        return 0
    else:
        print("\n✗ 部分测试失败，请检查上述错误信息。")
        return 1

if __name__ == "__main__":
    sys.exit(main())
