# Stripe API 版本升级补丁
# 用于快速修复 PayPal payment_method_types 问题

## 🎯 快速应用补丁

### 方法 1：直接修改代码文件

打开 `stripe_checkout.py`，找到第 37-40 行：

```python
# 修改前（第 37-40 行）
PAYPAL_STRIPE_VERSION = (
    "2020-08-27;custom_checkout_beta=v1; "
    "checkout_server_update_beta=v1; checkout_manual_approval_preview=v1"
)

# 修改后
PAYPAL_STRIPE_VERSION = (
    "2025-03-31.basil; "
    "checkout_server_update_beta=v1; checkout_manual_approval_preview=v1"
)
```

**关键变化**：
- ❌ 移除：`2020-08-27;custom_checkout_beta=v1`（可能已废弃）
- ✅ 使用：`2025-03-31.basil`（当前稳定版本）
- ✅ 保留：`checkout_server_update_beta` 和 `checkout_manual_approval_preview`

### 方法 2：使用 Git 补丁文件

```bash
# 创建补丁文件
cat > /tmp/stripe_api_upgrade.patch << 'EOF'
--- a/stripe_checkout.py
+++ b/stripe_checkout.py
@@ -34,7 +34,7 @@ STRIPE_VERSION_FULL = (
     "checkout_manual_approval_preview=v1"
 )
 DEFAULT_STRIPE_RUNTIME_VERSION = "6f8494a281"
-PAYPAL_STRIPE_VERSION = (
-    "2020-08-27;custom_checkout_beta=v1; "
+PAYPAL_STRIPE_VERSION = (
+    "2025-03-31.basil; "
     "checkout_server_update_beta=v1; checkout_manual_approval_preview=v1"
 )
EOF

# 应用补丁
cd E:\mygit\pay153-checkout-link
git apply /tmp/stripe_api_upgrade.patch
```

---

## 🧪 验证补丁

### 验证 1：查看修改
```bash
git diff stripe_checkout.py
```

应该显示：
```diff
- PAYPAL_STRIPE_VERSION = (
-     "2020-08-27;custom_checkout_beta=v1; "
+ PAYPAL_STRIPE_VERSION = (
+     "2025-03-31.basil; "
      "checkout_server_update_beta=v1; checkout_manual_approval_preview=v1"
  )
```

### 验证 2：运行测试脚本
```bash
# 1. 获取一个测试 session_id
# 2. 使用美国代理
python test_stripe_api_versions.py "cs_live_xxxxx" "socks5://proxy:port"
```

### 验证 3：完整提链测试
```bash
# 重启服务
python app.py

# 测试提链（日志中应该看到 pm=['card', 'paypal']）
```

---

## 🔄 回滚补丁

如果升级后有问题，可以回滚：

```bash
# 方法 1：Git 回滚
git checkout stripe_checkout.py

# 方法 2：手动改回
# 将 PAYPAL_STRIPE_VERSION 改回：
# "2020-08-27;custom_checkout_beta=v1; ..."
```

---

## 📋 预期日志变化

### 修复前
```
[stripe] init ok version=2020-08-27 amount=0 currency=usd pm=['card']
RuntimeError: 当前 checkout 未开放 paypal，可用方式：card
```

### 修复后
```
[stripe] init ok version=2025-03-31.basil amount=0 currency=usd pm=['card', 'paypal']
PayPal 已确认可用，正在应用优惠
```

---

## ⚠️ 重要提醒

1. **备份原文件**
   ```bash
   cp stripe_checkout.py stripe_checkout.py.backup
   ```

2. **测试前准备**
   - 确保有高质量美国代理
   - 确保 Stripe Dashboard 已启用 PayPal
   - 测试用 session_id 需要是有效的

3. **如果仍然失败**
   - 运行 `test_stripe_api_versions.py` 测试所有版本
   - 检查是否是代理 IP 风控问题
   - 查看 `.claude/stripe-api-upgrade-guide.md` 完整文档

---

## 🎯 一键应用（Windows）

创建批处理脚本 `apply_stripe_fix.cmd`：

```cmd
@echo off
echo ========================================
echo Stripe API 版本升级补丁
echo ========================================
echo.

echo [1/4] 备份原文件...
copy stripe_checkout.py stripe_checkout.py.backup
echo     ✓ 已备份到 stripe_checkout.py.backup
echo.

echo [2/4] 应用补丁...
powershell -Command "(Get-Content stripe_checkout.py) -replace '2020-08-27;custom_checkout_beta=v1;', '2025-03-31.basil;' | Set-Content stripe_checkout.py"
echo     ✓ 已更新 PAYPAL_STRIPE_VERSION
echo.

echo [3/4] 验证修改...
findstr "2025-03-31.basil" stripe_checkout.py >nul
if %errorlevel% == 0 (
    echo     ✓ 补丁应用成功
) else (
    echo     ✗ 补丁应用失败
    echo     正在恢复备份...
    copy stripe_checkout.py.backup stripe_checkout.py
    exit /b 1
)
echo.

echo [4/4] 完成
echo.
echo ========================================
echo 下一步：
echo 1. 重启服务：python app.py
echo 2. 运行测试：python test_stripe_api_versions.py
echo 3. 测试提链：查看日志 pm=['card', 'paypal']
echo.
echo 如需回滚：copy stripe_checkout.py.backup stripe_checkout.py
echo ========================================
pause
```

运行：
```cmd
apply_stripe_fix.cmd
```

---

## 🎯 总结

**这个补丁解决的问题**：
- ✅ 升级 Stripe API 从 2020 年 beta 版本到 2025 年稳定版本
- ✅ 移除可能已废弃的 `custom_checkout_beta=v1`
- ✅ 修复 `payment_method_types` 不包含 PayPal 的问题

**适用场景**：
- ✅ 测试脚本显示 "2025 基础版本" 成功
- ✅ 公开网站能跑通，你的本地不行
- ✅ 错误信息是 "checkout does not expose PayPal"

**不适用场景**（需要其他解决方案）：
- ❌ 所有 API 版本测试都失败（代理 IP 风控问题）
- ❌ 错误是 "generic_decline"（PayPal 风控问题）
- ❌ 测试成功但实际提链失败（优惠/代理问题）
