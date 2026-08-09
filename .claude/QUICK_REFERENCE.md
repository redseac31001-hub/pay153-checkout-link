# 🎯 快速参考卡片 - PayPal 提链修复

## 📌 立即执行（3步）

```cmd
# 第 1 步：诊断问题
python diagnose.py --proxy "socks5://your-proxy:port"

# 第 2 步：应用修复
apply_stripe_fix.cmd

# 第 3 步：测试验证
python test_stripe_api_versions.py "cs_live_xxx" "proxy"
```

---

## 🔴 关键修复

### 修复 1：升级 Stripe API 版本（最重要）

**问题**：使用 2020 年 beta 版本 → `pm=['card']` 没有 paypal

**修复**：
```python
# stripe_checkout.py:37-40
# 改为：
PAYPAL_STRIPE_VERSION = (
    "2025-03-31.basil; "
    "checkout_server_update_beta=v1; checkout_manual_approval_preview=v1"
)
```

**快速应用**：双击 `apply_stripe_fix.cmd`

---

### 修复 2：更换高质量代理

**问题**：数据中心 IP → generic_decline 80%+

**测试**：
```bash
curl -x "socks5://proxy:port" https://ipinfo.io/json
# 查看 "org" 字段，避免 "Hosting"/"Datacenter"
```

**要求**：
- ✅ 住宅 IP
- ✅ US/GB/CA/AU 等主流地区
- ❌ 避免数据中心 IP

---

## ✅ 已完成修复

1. ✅ 优惠策略优化（前 3 轮分离优惠）
2. ✅ 轮询次数增加（6 → 12 次）
3. ✅ 错误诊断增强

---

## 📊 预期效果

| 场景 | 修复前 | 修复后 |
|------|--------|--------|
| **API 版本** | `pm=['card']` | `pm=['card','paypal']` |
| **成功率（TH代理）** | 0-20% | 40-60% |
| **成功率（住宅IP）** | 0-20% | 70-90% |

---

## 🚨 常见错误

### 错误 1：`checkout does not expose PayPal: card`
- **原因**：API 版本过时
- **修复**：`apply_stripe_fix.cmd`

### 错误 2：`generic_decline`
- **原因**：代理 IP 风控
- **修复**：更换住宅 IP

### 错误 3：轮询超时
- **原因**：轮询次数不够
- **修复**：已修复（12 次）

---

## 📚 完整文档

- 📖 **FINAL_SUMMARY.md** - 完整总结
- 📖 **EXECUTION_CHECKLIST.md** - 执行清单
- 📖 **stripe-api-upgrade-guide.md** - API 升级指南
- 📖 **QUICK_FIX_PATCH.md** - 快速补丁

---

## 🔧 工具箱

- 🔍 `diagnose.py` - 一键诊断
- 🧪 `test_stripe_api_versions.py` - 测试 API
- 🔧 `apply_stripe_fix.cmd` - 应用补丁
- ✅ `verify_config.cmd` - 验证配置

---

## 💡 成功标志

**日志中应该看到**：
```
[stripe] init ok version=2025-03-31.basil pm=['card', 'paypal']
                         ↑ 新版本              ↑ 包含 paypal
第 7/7 步：PayPal agreements/approve 链接生成完成
```

---

## 📞 故障排查

**如果仍然失败，检查：**
1. 代理质量（`diagnose.py --proxy xxx`）
2. Stripe Dashboard 是否启用 PayPal
3. 是否使用主流地区代理（US/GB/CA）
4. 完整日志（查找具体错误信息）

---

**保存此卡片以便快速参考！** 🚀
