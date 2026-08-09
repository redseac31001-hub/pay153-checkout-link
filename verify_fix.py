#!/usr/bin/env python3
"""验证 PayPal 白名单修复是否生效"""

import sys
import os

# 确保从当前目录导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import stripe_checkout as sc

    print("=" * 60)
    print("PayPal 白名单验证")
    print("=" * 60)

    countries = getattr(sc, "PAYPAL_ORDER_COUNTRIES", [])

    print(f"\n当前白名单: {countries}")
    print(f"\n白名单国家数量: {len(countries)}")

    if "GB" in countries:
        print("\n✅ 修复成功！GB 已在白名单中")
        print("\n预期行为：")
        print("  - GB 代理将使用 GB/GBP 创建 Checkout")
        print("  - 不再回退到 DE/EUR")
        print("  - 不再出现 400 错误")
        sys.exit(0)
    else:
        print("\n❌ 修复未生效！GB 不在白名单中")
        print("\n可能原因：")
        print("  1. Python 使用了缓存的 .pyc 文件")
        print("  2. 导入了错误的模块")
        print("  3. 服务未正确重启")
        print("\n解决方案：")
        print("  1. 删除所有 .pyc 文件和 __pycache__ 目录")
        print("  2. 彻底停止所有 Python 进程")
        print("  3. 重新启动服务")
        sys.exit(1)

except Exception as e:
    print(f"\n❌ 导入失败: {e}")
    print("\n请确保在项目根目录运行此脚本")
    sys.exit(1)
