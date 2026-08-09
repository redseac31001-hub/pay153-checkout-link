#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快速测试 Stripe API 版本是否可用"""
import os
import sys
import io

# 修复 Windows 控制台编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 读取当前 API 版本
with open("stripe_checkout.py", "r", encoding="utf-8") as f:
    content = f.read()
    
# 提取版本号
import re
match = re.search(r'PAYPAL_STRIPE_VERSION = \(\s*"([^"]+)"', content)
if match:
    current_version = match.group(1)
    print(f"当前使用的 Stripe API 版本：{current_version}")
    print()
    
    if "2020-08-27" in current_version:
        print("WARNING: 你正在使用 2020 年（6 年前）的 API 版本")
        print("WARNING: 这个版本包含 beta 功能：custom_checkout_beta=v1")
        print()
        print("DIAGNOSIS: 这可能是 422 错误的根本原因！")
        print()
        print("SOLUTION: 建议升级到：2025-03-31.basil")
        print()
        print("执行以下命令应用升级：")
        print("   apply_stripe_fix.cmd")
    else:
        print("OK: API 版本看起来是新的")
else:
    print("ERROR: 无法找到 API 版本定义")

