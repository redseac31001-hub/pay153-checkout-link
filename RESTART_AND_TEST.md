# 🚀 重启服务和测试指南

## 修复已完成 ✅

所有代码修复已应用并提交到分支 `wip/paypal-proxy-debug`

---

## 📋 重启服务步骤

### 方式 1：如果服务正在运行

```bash
# 1. 停止当前服务
taskkill /F /IM python.exe

# 2. 等待 2 秒
timeout /t 2

# 3. 重新启动服务
python app.py
```

### 方式 2：如果使用 systemd/supervisor

```bash
# 根据你的部署方式
sudo systemctl restart pay153
# 或
sudo supervisorctl restart pay153
```

### 方式 3：使用提供的脚本

```bash
# 双击运行
restart_with_fix.cmd

# 或命令行
cmd /c restart_with_fix.cmd
```

---

## 🧪 测试步骤

### 测试 1：验证 API 版本（快速测试）

**启动服务后，观察日志中的版本信息**：

```
预期看到：
[stripe] init ok version=2025-03-31.basil ... pm=['card', 'paypal']
                         ↑ 新版本                    ↑ 包含 paypal
```

**如果看到**：
- ❌ `pm=['card']` → API 版本可能未生效，检查是否重启
- ✅ `pm=['card', 'paypal']` → 成功！

---

### 测试 2：完整提链测试

**使用网页或 API 测试**：

```bash
# 示例：使用 curl 测试
curl -X POST http://localhost:18082/api/checkout \
  -H "Content-Type: application/json" \
  -d '{
    "token": "YOUR_TOKEN",
    "plan": "plus",
    "link_type": "paypal",
    "country": "US",
    "currency": "USD",
    "entry_proxies": ["socks5://proxy1:port"],
    "exit_proxies": ["socks5://proxy2:port"],
    "retry_count": 10,
    "use_promo": true,
    "promo_campaign": "chatgpt20"
  }'
```

---

### 测试 3：观察日志

**关键日志指标**：

#### ✅ 成功指标
```
[stripe] init ok version=2025-03-31.basil ... pm=['card', 'paypal']
PayPal 已确认可用，正在应用优惠
第 7/7 步：PayPal agreements/approve 链接生成完成
✅ 提链成功！
```

#### ⚠️ 风控指标（正常，需要重试）
```
[stripe] ⚠️ generic_decline 检测（常见原因）：
  1) 代理 IP 被 PayPal 风控
  2) 账单地址与 PayPal 账户国家不匹配
  3) Stripe 指纹字段冲突
```

#### ❌ 失败指标（需要排查）
```
当前 checkout 未开放 paypal（可能由零金额优惠导致），可用方式：card
# 说明 API 版本可能未生效，或优惠策略有问题
```

---

## 📊 预期效果

### 修复前（使用旧 API）
```
10 次重试：
├─ payment_method_types 错误: 5-8 次（50-80%）
├─ generic_decline: 2-5 次（20-50%）
└─ 成功率: 0-10%
```

### 修复后（使用新 API + TH 代理）
```
10 次重试：
├─ payment_method_types 错误: < 1 次（< 10%）✅
├─ generic_decline: 3-4 次（30-40%）
├─ TLS 错误: 1 次（10%）
└─ 成功率: 40-60% ⬆️⬆️
```

### 进一步优化（更换高质量住宅代理）
```
10 次重试：
├─ generic_decline: 1-2 次（10-20%）
└─ 成功率: 70-90% ⬆️⬆️⬆️
```

---

## 🔍 故障排查

### 问题 1：重启后仍然显示 `pm=['card']`

**可能原因**：
- 代码未重新加载
- 缓存未清除
- 使用了旧的 Python 进程

**解决方法**：
```bash
# 1. 强制杀死所有 Python 进程
taskkill /F /IM python.exe

# 2. 检查文件是否真的修改了
grep "2025-03-31.basil" stripe_checkout.py

# 3. 清除 Python 缓存
find . -type d -name __pycache__ -exec rm -rf {} +
find . -type f -name "*.pyc" -delete

# 4. 重新启动
python app.py
```

---

### 问题 2：仍然出现大量 generic_decline

**说明**：
- API 版本已修复（payment_method_types 正常）
- 但代理 IP 被 PayPal 风控

**解决方法**：
1. **更换代理池**（推荐）：
   - TH 代理池质量可能不足
   - 使用高质量住宅代理
   - 或使用静态住宅 IP

2. **增加重试次数**：
   ```python
   retry_count: 15  # 从 10 增加到 15
   ```

3. **检查账单地址匹配**：
   - 确保代理国家与账单国家一致
   - 或使用白名单国家（DE, US, NL）

---

### 问题 3：TLS 连接错误

**说明**：
- 代理链的 TLS 握手失败

**解决方法**：
```bash
# 检查本地网关状态
netstat -an | grep 9697

# 如果网关有问题，临时禁用代理链
set PAY153_PROXY_PRE_PROXY=disabled
python app.py
```

---

## 📞 如果仍有问题

提供以下信息：

1. **完整提链日志**（包含 Stripe 初始化部分）
2. **API 版本确认**：
   ```bash
   grep "PAYPAL_STRIPE_VERSION" stripe_checkout.py
   ```
3. **payment_method_types 值**：
   ```
   从日志中找到：pm=[...]
   ```
4. **错误类型统计**：
   - payment_method_types 错误：X 次
   - generic_decline 错误：X 次
   - TLS 错误：X 次

---

## 🎯 成功标志

**当你看到以下日志时，说明修复成功**：

```
========== 提链尝试 1/10 ==========
[stripe] init ok version=2025-03-31.basil amount=0 currency=usd pm=['card', 'paypal']
                         ↑ 新版本                                    ↑ 包含 paypal
PayPal 已确认可用，正在应用优惠
PayPal 优惠策略：分离应用（Checkout 创建后更新）
第 1/7 步：创建 Stripe Checkout Session
第 2/7 步：初始化 Stripe Elements
第 3/7 步：应用促销优惠到 Checkout
第 4/7 步：确认优惠已生效（amount=0）
第 5/7 步：提交 PayPal SetupIntent
第 6/7 步：等待 PayPal merchant approval
第 7/7 步：PayPal agreements/approve 链接生成完成
✅ 提链成功！

结果：
  账户邮箱：test@example.com
  支付方式：PAYPAL
  促销状态：已生效 · 今日应付 0
  短链接：https://checkout.openai.com/pay/...
```

---

## 📚 相关文档

- `.claude/README.md` - 完整文档索引
- `.claude/QUICK_REFERENCE.md` - 快速参考
- `.claude/EXECUTION_CHECKLIST.md` - 执行清单
- `.claude/paypal-errors-diagnosis.md` - 错误诊断手册

---

**祝你提链成功！** 🚀
