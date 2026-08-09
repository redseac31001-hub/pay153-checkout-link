# PayPal 轮询 12 次仍失败 - 深度诊断

## 🔍 当前状态

### ✅ 已确认

1. **配置生效**：错误信息显示 "轮询 12 次"（不是 6 次）
2. **approve 成功**：`[stripe] manual_approval approve: 200 {"result":"approved"}`
3. **代理可用**：approve 成功说明代理池质量可接受
4. **PayPal 可用**：`pm=['card', 'paypal']` 包含 PayPal

### ❌ 问题

approve 成功后，轮询 12 次（12 秒）仍未从 Stripe 获取到 PayPal 跳转地址。

---

## 🤔 可能的原因

### 原因 1：Stripe API 变化或 PayPal 集成关闭（最可能）

**证据**：
- 所有本地测试都表现一致
- approve 成功但后续无跳转
- 时间节点：2024-08-09

**可能性**：
1. **Stripe 关闭了 manual_approval 的 PayPal 支持**
   - manual_approval 是 beta 功能
   - Stripe 可能停止支持或改变了实现方式

2. **PayPal 与 Stripe 的集成出现问题**
   - PayPal webhook 回调失败
   - Stripe 无法从 PayPal 获取跳转地址

3. **Stripe API 版本过期**
   ```python
   STRIPE_VERSION_BASE = "2025-03-31.basil"
   PAYPAL_STRIPE_VERSION = "2020-08-27;custom_checkout_beta=v1"
   ```
   注意：PayPal 使用的是 **2020 年的 API 版本**

### 原因 2：代理链延迟过大（可能性较低）

**如果是这个原因**：
- 12 秒仍不够
- 需要 > 12 秒才能获取跳转地址

**概率**：较低，因为 12 秒已经很长了

### 原因 3：submission_attempt 状态异常

**需要查看**：
- `sub_state` 是什么？（processing/requires_approval/其他？）
- `setup_intent.status` 是什么？
- `next_action.type` 是什么？

---

## 🔧 诊断步骤

### 步骤 1：重启服务并重新测试（收集详细日志）

**修改已生效**：
- ✅ 增加了 `next_action_type` 日志
- ✅ 失败时自动保存 `_poll_last_response.json`

**操作**：
```cmd
# 1. 停止服务
taskkill /F /IM python.exe

# 2. 重新启动
python app.py

# 3. 重新测试提链
```

**观察日志**：
```
[stripe] approve 后 poll 1/12: sub_state=? payment_status=? setup_status=? next_action_type=? decline_code=? decline_message=?
```

**关键信息**：
- `sub_state` - submission_attempt 的状态
- `setup_status` - setup_intent 的状态
- `next_action_type` - 是否有 redirect_to_url 等类型

### 步骤 2：分析保存的响应

**测试失败后**：
```cmd
# 查看保存的最后一次响应
type _poll_last_response.json

# 或用 Python 格式化查看
python -m json.tool _poll_last_response.json
```

**关键字段**：
```json
{
  "submission_attempt": {
    "state": "processing"  // 或其他状态？
  },
  "setup_intent": {
    "status": "?",
    "next_action": {
      "type": "?",
      "redirect_to_url": {
        "url": "?"
      }
    }
  }
}
```

### 步骤 3：检查线上环境的差异

**对比**：
- 线上的 Stripe API 版本
- 线上的 PayPal 流程（是否也走 manual_approval？）
- 线上是否也出现相同问题

**关键问题**：
1. 线上的提链流程是什么？
2. 线上是否也在 approve 后轮询？
3. 线上的成功日志是什么样的？

---

## 💡 可能的解决方案

### 方案 1：升级 Stripe API 版本（如果是版本问题）

**当前 PayPal 使用的版本**：
```python
PAYPAL_STRIPE_VERSION = "2020-08-27;custom_checkout_beta=v1"
```

**问题**：2020 年的版本，可能已经过期

**解决**：
```python
# 尝试使用新版本
PAYPAL_STRIPE_VERSION = "2025-03-31.basil; checkout_manual_approval_preview=v1"
```

### 方案 2：更换 PayPal 集成方式（如果 manual_approval 不再支持）

**当前方式**：
```
confirm → requires_approval → merchant approve → poll redirect
```

**可能需要改为**：
```
confirm → 直接返回 redirect_url（不走 manual_approval）
```

### 方案 3：增加更详细的错误处理

**在轮询失败时**：
- 记录 submission_attempt 的完整状态
- 记录 setup_intent/payment_intent 的完整状态
- 尝试直接从 PayPal API 获取跳转地址

### 方案 4：使用备用流程（如果主流程不可用）

**Fallback 策略**：
```python
if poll_redirect_after_approve 失败:
    尝试直接 confirm（不走 manual_approval）
    或使用 hosted checkout
```

---

## 🎯 立即操作

### 1. 重启服务应用新日志

```cmd
taskkill /F /IM python.exe
python app.py
```

### 2. 重新测试提链并收集日志

**观察**：
- `sub_state` 的值
- `setup_status` 的值
- `next_action_type` 的值
- 是否生成 `_poll_last_response.json`

### 3. 提供完整日志

**需要的信息**：
```
完整的轮询日志（所有 poll 1/12 到 poll 12/12）
示例：
[stripe] approve 后 poll 1/12: sub_state=processing payment_status= setup_status=requires_action next_action_type=redirect_to_url decline_code= decline_message=
[stripe] approve 后 poll 2/12: sub_state=processing payment_status= setup_status=requires_action next_action_type=redirect_to_url decline_code= decline_message=
...
```

### 4. 提供 _poll_last_response.json

**如果文件生成了**：
```cmd
type _poll_last_response.json
```

**或者**：
```cmd
python -m json.tool _poll_last_response.json > poll_response_formatted.json
type poll_response_formatted.json
```

---

## 📊 判断标准

### 如果日志显示

**场景 A：sub_state 一直是 processing**
```
[stripe] approve 后 poll 1/12: sub_state=processing next_action_type=none
[stripe] approve 后 poll 12/12: sub_state=processing next_action_type=none
```
**说明**：Stripe 确实没有生成跳转地址（可能是 API 问题）

**场景 B：next_action_type 有值但无法提取**
```
[stripe] approve 后 poll 1/12: next_action_type=redirect_to_url
```
**说明**：跳转地址存在但提取逻辑有问题

**场景 C：setup_status 异常**
```
[stripe] approve 后 poll 1/12: setup_status=canceled
```
**说明**：setup_intent 被取消或失败

**场景 D：出现 decline_code**
```
[stripe] approve 后 poll 3/12: decline_code=generic_decline
```
**说明**：PayPal 拒绝（代理 IP 风控）

---

## 🚨 紧急验证

### 验证 1：线上环境是否也失败

**问题**：
- 线上提链现在能成功吗？
- 线上是否也出现"approve 成功但无跳转"？

**如果线上也失败**：
- 说明是 Stripe/PayPal 整体问题
- 不是你的代码问题

**如果线上仍成功**：
- 对比线上和本地的差异
- 检查 Stripe API 版本、代理配置等

### 验证 2：检查 Stripe Dashboard

**登录 Stripe Dashboard**：
1. 查看最近的 Checkout Session
2. 查看 Setup Intent 状态
3. 查看是否有错误日志

---

## 📞 需要的反馈信息

测试后请提供：

1. **完整的轮询日志**（从 poll 1/12 到 poll 12/12）
2. **_poll_last_response.json 的内容**（如果生成）
3. **线上环境的状态**（是否也失败？）
4. **Stripe Dashboard 的错误信息**（如果有）

---

**修复时间**：2024-08-09  
**问题类型**：approve 成功但无跳转地址  
**诊断状态**：等待详细日志  
**下一步**：重启服务并收集详细日志
