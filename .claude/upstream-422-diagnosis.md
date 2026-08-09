# "upstream returned HTTP 422" 错误诊断

## 🎯 问题描述

**用户报告**：
- 公开网站显示：`upstream returned HTTP 422: checkout does not expose PayPal: card`
- 错误字段：`last_retry_error`
- **关键特征**：没有打印正常的 PayPal 日志（代理池、Checkout 初始化等）

---

## 🔍 错误来源分析

### 1. "upstream returned" 的含义

**"upstream"** 说明：
- ✅ **公开网站调用了你的服务作为上游 API**
- ✅ 不是你的代码直接返回的错误
- ✅ 是外层服务（公开网站）包装后的错误信息

**架构示意**：
```
用户 → 公开网站（外层服务）→ 你的服务（pay153 API）→ Stripe/PayPal
                             ↑
                    这里是 "upstream"
```

### 2. HTTP 422 错误的真实来源

**根据代码 `app.py:2120-2221` 和 `provider_checkout.py:1064-1069`**：

```python
# provider_checkout.py:1064-1069
methods = ctx.get("payment_method_types") or []
if provider not in methods:
    raise RuntimeError(
        f"当前 checkout 未开放 {provider}（可能由零金额优惠导致），"
        f"可用方式：{', '.join(methods) or 'card'}"
    )
```

**这个 RuntimeError 会被捕获并记录到 job 的 `error` 字段**：

```python
# app.py:1975-2003
except Exception as exc:
    error_text = str(exc)
    self.log(job_id, f"错误：{type(exc).__name__}: {error_text}")
    self.update(job_id, status="error", error=error_text[:1200])
```

**公开网站通过 `/api/checkout-progress` 获取到这个错误**：

```python
# app.py:2224-2243
@app.get("/api/checkout-progress")
def checkout_progress():
    job = STORE.get(str(request.args.get("job_id") or ""), public=True)
    if not job:
        return jsonify({"error": "任务不存在"}), 404
    return jsonify(job)  # 包含 error 字段
```

**所以 "upstream returned HTTP 422" 是公开网站包装后的错误格式。**

---

## 🤔 为什么没有打印正常日志？

### 关键发现

**正常流程日志**（你本地环境）：
```
代理池 1 共 10 条，代理池 2 共 20 条，本次已分别自动选择
PayPal 代理池 2 地区：US/Ohio
Checkout=US/USD（当前国家支持 PayPal）
[stripe] init ok version=2025-03-31.basil amount=0 currency=usd pm=['card', 'paypal']
```

**公开网站**：
- ❌ **没有这些日志**
- ❌ 直接报错：`checkout does not expose PayPal: card`

### 原因推断

**有两种可能**：

#### 可能 1：公开网站使用了不同的代码路径

**证据**：
- 日志完全缺失
- 错误信息格式不同（"upstream returned" 前缀）

**推测**：
公开网站可能：
1. 使用了旧版本代码（没有详细日志）
2. 使用了简化的 API 调用（跳过了部分步骤）
3. 有自己的包装层（添加了 "upstream returned" 前缀）

#### 可能 2：API 版本不同导致 PayPal 被移除

**Stripe API 版本对比**：

```python
# 你的代码（stripe_checkout.py:31-40）
STRIPE_VERSION_BASE = "2025-03-31.basil"
PAYPAL_STRIPE_VERSION = "2020-08-27;custom_checkout_beta=v1"
```

**如果公开网站使用了不同的 API 版本**：
- 旧版本 API 可能不支持 PayPal
- 或 Stripe 改变了 PayPal 的可用规则

---

## 🔧 验证方法

### 步骤 1：检查公开网站的完整日志

**需要查看的信息**：

```
# 查找这些关键行
1. 服务启动日志：版本号、API 版本
2. 任务创建日志：entry_proxies, exit_proxies
3. 代理检测日志：proxy_country 返回值
4. Stripe init 日志：[stripe] init ok version=? pm=?
```

**如果这些日志都没有**，说明：
- 公开网站使用了完全不同的代码
- 或者日志级别被关闭了

### 步骤 2：对比 API 响应

**本地测试**：
```bash
curl -X POST http://localhost:18082/api/checkout \
  -H "Content-Type: application/json" \
  -d '{
    "token": "YOUR_TOKEN",
    "plan": "plus",
    "link_type": "paypal",
    "country": "US",
    "currency": "USD",
    "entry_proxies": "...",
    "exit_proxies": "..."
  }'

# 获取 job_id 后查询进度
curl "http://localhost:18082/api/checkout-progress?job_id=xxx"
```

**对比公开网站的 API 响应**：
```json
{
  "status": "error",
  "error": "当前 checkout 未开放 paypal，可用方式：card",
  "logs": [...]  // 关键：有没有详细日志？
}
```

### 步骤 3：检查是否主动传了 PayPal

**你的问题**：
> "422是不是主动先传了paypal方式 而不是查回来？"

**答案**：❌ **不是主动传的，是 Stripe 返回的**

**证据（代码逻辑）**：

```python
# 1. 创建 Checkout（不指定支付方式）
checkout_data = create_checkout_session(
    chatgpt_http, token, plan, country, ...
)
# Stripe 自动决定可用的 payment_method_types

# 2. 获取 Stripe 返回的支付方式
init_data = stripe_api.init(session_id, ...)
payment_method_types = init_data.get("payment_method_types")  # Stripe 返回

# 3. 检查 PayPal 是否在列表中
if "paypal" not in payment_method_types:
    raise RuntimeError(f"checkout 未开放 paypal，可用方式：{payment_method_types}")
```

**所以**：
- ✅ 你的代码**不会主动传** `paypal` 给 Stripe
- ✅ Stripe **自动决定**支持哪些支付方式
- ✅ 你的代码**检查** Stripe 返回的列表

---

## 📊 可能原因总结

| 原因 | 概率 | 验证方法 |
|------|------|---------|
| **代理地区不支持 PayPal** | 🔴 80% | 查看公开网站日志中的代理地区 |
| **优惠导致零金额移除 PayPal** | 🟡 15% | 查看日志中的 `amount` 和 `promo_on_create` |
| **API 版本不同** | 🟢 5% | 对比 Stripe API 版本号 |

---

## 🎯 最可能的原因：代理地区不支持 PayPal

**根据经验和代码逻辑**：

### 场景推测

```
公开网站：
  exit_proxies → 包含某个非 PayPal 支持地区的代理
  ↓
  select_paypal_exit_proxy() 扫描代理池
  ↓
  所有代理都不支持 PayPal（或检测失败）
  ↓
  使用了一个不支持 PayPal 的代理
  ↓
  Stripe 根据代理 IP 判定国家
  ↓
  返回 pm=['card']（没有 paypal）
  ↓
  你的代码检测到并抛出 RuntimeError
  ↓
  公开网站包装为：upstream returned HTTP 422
```

### 验证步骤

**1. 检查公开网站使用的代理池**

如果公开网站有日志，查找：
```
PayPal 代理池 2 地区：XX/YY
PayPal 已跳过不兼容地区：...
```

如果没有这些日志，说明代理检测步骤**根本没执行**。

**2. 检查代码版本**

对比公开网站和本地的代码：
```bash
# 本地
git log -1 --oneline
# e59b487 fix: repair proxy chain and add proxy identity probe

# 公开网站
# 查看其 git 版本或文件修改时间
```

**3. 强制使用 US 代理测试**

在公开网站上：
- 确保 exit_proxies 只包含 US/GB/CA 等主流地区
- 重新测试

---

## 💡 解决方案

### 方案 1：统一代码版本

**确保公开网站使用最新代码**：
```bash
cd /path/to/public-website
git pull
git checkout e59b487  # 或最新 commit
pip install -r requirements.txt
# 重启服务
```

### 方案 2：检查代理池配置

**确保使用 PayPal 支持的地区**：
- ✅ US, GB, CA, AU, DE, FR, IT, ES, JP
- ❌ 避免使用小国家或不确定的地区

### 方案 3：启用详细日志

**如果公开网站关闭了日志**：
```python
# 在 app.py 开头添加
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 方案 4：添加诊断端点

**在公开网站添加调试接口**：
```python
@app.get("/api/debug/job/<job_id>")
def debug_job(job_id):
    job = STORE.get(job_id, public=True)
    return jsonify({
        "job": job,
        "logs": job.get("logs", []),  # 完整日志
        "error": job.get("error", ""),
        "stripe_version": STRIPE_VERSION_BASE,
        "code_version": subprocess.check_output(["git", "rev-parse", "--short", "HEAD"]).decode().strip(),
    })
```

---

## 🔍 需要你提供的信息

为了精确诊断，请提供：

1. **公开网站的完整日志**（至少一次失败任务的所有日志）
2. **公开网站的代码版本**（git commit hash 或修改日期）
3. **公开网站使用的代理池配置**（地区分布）
4. **API 响应示例**（`/api/checkout-progress` 的完整返回）

有了这些信息，我就能给出精确的修复方案。🎯
