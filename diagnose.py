"""
一键诊断工具 - 快速检测 PayPal 提链问题

运行此脚本可以自动检测：
1. 代码版本是否需要升级
2. 代理质量是否合格
3. Stripe API 版本是否过时
4. 配置是否正确
"""

import os
import sys
import subprocess
import json

def print_header(title):
    print(f"\n{'='*60}")
    print(f"{title:^60}")
    print(f"{'='*60}\n")

def print_step(step, total, desc):
    print(f"[{step}/{total}] {desc}")

def check_code_version():
    """检查代码版本"""
    print_step(1, 5, "检查代码版本...")

    try:
        with open("stripe_checkout.py", "r", encoding="utf-8") as f:
            content = f.read()

        if "2020-08-27;custom_checkout_beta=v1" in content:
            print("    ❌ 使用旧版本 API (2020-08-27)")
            print("    💡 建议：运行 apply_stripe_fix.cmd 升级")
            return False
        elif "2025-03-31.basil" in content:
            print("    ✅ 使用新版本 API (2025-03-31.basil)")
            return True
        else:
            print("    ⚠️  未识别的 API 版本")
            return None
    except Exception as e:
        print(f"    ❌ 错误：{e}")
        return None

def check_proxy_quality(proxy):
    """检查代理质量"""
    print_step(2, 5, "检查代理质量...")

    if not proxy:
        print("    ⚠️  未提供代理，跳过检测")
        print("    提示：使用参数 --proxy 指定代理")
        return None

    print(f"    代理地址：{proxy}")

    try:
        # 使用 curl 测试代理
        cmd = f'curl -x "{proxy}" -s https://ipinfo.io/json'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)

        if result.returncode == 0:
            data = json.loads(result.stdout)

            print(f"    IP: {data.get('ip', 'unknown')}")
            print(f"    国家: {data.get('country', 'unknown')}")
            print(f"    城市: {data.get('city', 'unknown')}")
            print(f"    ISP: {data.get('org', 'unknown')}")

            # 检查是否是数据中心 IP
            org = data.get('org', '').lower()
            is_datacenter = any(keyword in org for keyword in [
                'hosting', 'datacenter', 'data center', 'cloud', 'server', 'vps'
            ])

            if is_datacenter:
                print("    ❌ 数据中心 IP（容易被风控）")
                print("    💡 建议：更换为住宅 IP")
                return False
            else:
                print("    ✅ 住宅 IP（质量较好）")
                return True
        else:
            print(f"    ❌ 代理连接失败：{result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print("    ❌ 代理连接超时")
        return False
    except Exception as e:
        print(f"    ❌ 错误：{e}")
        return False

def check_env_config():
    """检查环境配置"""
    print_step(3, 5, "检查环境配置...")

    # 检查 .env 文件
    if os.path.exists(".env"):
        print("    ✅ .env 文件存在")

        try:
            with open(".env", "r") as f:
                content = f.read()

            if "PAYPAL_APPROVE_POLL_ATTEMPTS" in content:
                import re
                match = re.search(r"PAYPAL_APPROVE_POLL_ATTEMPTS\s*=\s*(\d+)", content)
                if match:
                    attempts = int(match.group(1))
                    print(f"    轮询次数配置：{attempts}")
                    if attempts >= 12:
                        print("    ✅ 轮询次数充足")
                    else:
                        print("    ⚠️  轮询次数较少，建议设为 12")
        except Exception as e:
            print(f"    ⚠️  读取 .env 失败：{e}")
    else:
        print("    ⚠️  .env 文件不存在（使用默认配置）")

    # 检查 python-dotenv
    try:
        import dotenv
        print("    ✅ python-dotenv 已安装")
    except ImportError:
        print("    ❌ python-dotenv 未安装")
        print("    💡 建议：pip install python-dotenv")
        return False

    return True

def check_dependencies():
    """检查依赖"""
    print_step(4, 5, "检查依赖...")

    required = {
        "curl_cffi": "curl-cffi（TLS 指纹）",
        "flask": "Flask（Web 服务）",
        "requests": "requests（HTTP 请求）",
    }

    all_ok = True
    for module, desc in required.items():
        try:
            __import__(module)
            print(f"    ✅ {desc}")
        except ImportError:
            print(f"    ❌ {desc} 未安装")
            all_ok = False

    if not all_ok:
        print("\n    💡 建议：pip install -r requirements.txt")

    return all_ok

def check_files():
    """检查关键文件"""
    print_step(5, 5, "检查关键文件...")

    required_files = {
        "stripe_checkout.py": "Stripe API 调用",
        "app.py": "主服务",
        "provider_checkout.py": "支付提供商处理",
    }

    all_ok = True
    for file, desc in required_files.items():
        if os.path.exists(file):
            print(f"    ✅ {file}（{desc}）")
        else:
            print(f"    ❌ {file}（{desc}）缺失")
            all_ok = False

    return all_ok

def generate_report(results):
    """生成诊断报告"""
    print_header("诊断报告")

    score = sum(1 for r in results.values() if r is True)
    total = len([r for r in results.values() if r is not None])

    print(f"总分：{score}/{total}")
    print()

    # 代码版本
    if results['code_version'] is False:
        print("❌ 关键问题：代码使用旧版本 Stripe API")
        print("   → 执行：apply_stripe_fix.cmd")
        print()

    # 代理质量
    if results['proxy_quality'] is False:
        print("❌ 关键问题：代理质量不合格（数据中心 IP）")
        print("   → 更换为高质量住宅 IP")
        print()
    elif results['proxy_quality'] is None:
        print("⚠️  警告：未测试代理质量")
        print("   → 使用 --proxy 参数重新运行诊断")
        print()

    # 依赖
    if results['dependencies'] is False:
        print("❌ 问题：缺少必要依赖")
        print("   → 执行：pip install -r requirements.txt")
        print()

    # 综合建议
    print("="*60)
    if score == total:
        print("✅ 所有检查通过！")
        print()
        print("下一步：")
        print("1. 运行 API 版本测试：")
        print("   python test_stripe_api_versions.py \"cs_live_xxx\" \"proxy\"")
        print()
        print("2. 执行完整提链测试")
    else:
        print("⚠️  发现问题，请先修复上述问题后再测试")
        print()
        print("修复顺序：")
        print("1. 升级代码版本（apply_stripe_fix.cmd）")
        print("2. 更换代理（如果质量不合格）")
        print("3. 安装依赖（pip install -r requirements.txt）")
        print("4. 重新运行诊断（python diagnose.py --proxy \"xxx\"）")

    print("="*60)

def main():
    print_header("PayPal 提链问题诊断工具")

    # 解析参数
    proxy = None
    if len(sys.argv) > 1:
        if sys.argv[1] == "--proxy" and len(sys.argv) > 2:
            proxy = sys.argv[2]
        elif not sys.argv[1].startswith("--"):
            proxy = sys.argv[1]

    if not proxy:
        proxy = os.getenv("TEST_PROXY")

    # 执行检查
    results = {}

    try:
        results['code_version'] = check_code_version()
        results['proxy_quality'] = check_proxy_quality(proxy)
        results['env_config'] = check_env_config()
        results['dependencies'] = check_dependencies()
        results['files'] = check_files()
    except KeyboardInterrupt:
        print("\n\n用户中断")
        sys.exit(1)

    # 生成报告
    generate_report(results)

    print("\n提示：使用 --proxy 参数可以测试代理质量")
    print("示例：python diagnose.py --proxy \"socks5://proxy:port\"")

if __name__ == "__main__":
    main()
