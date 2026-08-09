# ✅ 事实核查：API 版本从未改变

## 🎯 关键发现：我的推测是**错误的**

### 事实检查结果

**初始版本（2026-07-21）**：
```python
PAYPAL_STRIPE_VERSION = (
    "2020-08-27;custom_checkout_beta=v1; "
    "checkout_server_update_beta=v1; checkout_manual_approval_preview=v1"
)
```

**最新版本（2026-08-06）**：
```python
PAYPAL_STRIPE_VERSION = (
    "2020-08-27;custom_checkout_beta=v1; "
    "checkout_server_update_beta=v1; checkout_manual_approval_preview=v1"
)
```

**结论**：✅ **API 版本字符串完全没有改动！**

---

## 🔍 那么真正改动了什么？

### 主要改动：代理链架构（proxy chain）

**新增代码（stripe_checkout.py:42-89）**：
```python
# 新增环境变量和代理前置逻辑
PROXY_PRE_PROXY_ENV = "PAY153_PROXY_PRE_PROXY"
DEFAULT_PROXY_PRE_PROXY = "socks5h://127.0.0.1:9697"

def proxy_pre_proxy() -> str | None:
    """Return the first-hop proxy for all configured proxy-pool exits."""
    # 本地网关 → 代理池的双层代理架构
    ...

def proxy_curl_options() -> dict:
    """Build curl options for the local first-hop proxy."""
    # 使用 CURLOPT_PRE_PROXY
    ...

def build_http(proxy):
    http = CffiSession(
        impersonate="chrome136",
        curl_options=proxy_curl_options() if proxy else ,  # ← 新增
    )
```

**改动含义**：
- ✅ 从**单层代理**改为**双层代理链**
- ✅ 本地网关（127.0.0.1:9697）→ 代理池出口
- ✅ 使用 `CURLOPT_PRE_PROXY` 实现链式代理

---

## 💡 重新分析：为什么现在不行了？

### 新假设 1：代理链配置问题（可能性：⭐⭐⭐⭐⭐）

**如果你没有配置本地网关**：
```python
# 代码期望存在：
DEFAULT_PROXY_PRE_PROXY = "socks5h://127.0.0.1:9697"

# 如果 127.0.0.1:9697 不存在：
→ 连接失败
→ 代理链断裂
→ 请求走错路径
→ 获取不到正确的 payment_method_types
```

**验证方法**：
```bash
# 检查本地是否有网关在监听
netstat -an | grep 9697

# 或
curl -x socks5h://127.0.0.1:9697 https://ipinfo.io/json
```

---

### 新假设 2：你使用了不同的代码分支（可能性：⭐⭐⭐⭐）

**关键问题**：
- 你当前运行的代码是哪个版本？
- 是 7-21 的旧版本（没有代理链）？
- 还是 8-06 的新版本（有代理链）？

**如果你运行的是旧版本**：
- 可能缺少某些关键修复
- 可能与公开网站的后端不兼容

**验证方法**：
```bash
# 检查当前代码
grep -n "proxy_pre_proxy" stripe_checkout.py
# 如果找不到 → 你运行的是旧版本
# 如果找到了 → 你运行的是新版本
```

---

### 新假设 3：环境变量配置差异（可能性：⭐⭐⭐⭐）

**新代码依赖环境变量**：
```python
PROXY_PRE_PROXY_ENV = "PAY153_PROXY_PRE_PROXY"
```

**如果你没有设置或设置错误**：
```bash
# 检查环境变量
echo $PAY153_PROXY_PRE_PROXY

# 或在 Python 中
import os
print(os.getenv("PAY153_PROXY_PRE_PROXY"))
```

**可能的问题**：
- ❌ 环境变量未设置 → 使用默认值（127.0.0.1:9697）
- ❌ 默认网关不存在 → 连接失败
- ❌ 设置为错误的值 → 代理链断裂

---

### 新假设 4：Stripe 仍然可能废弃了旧版本（可能性：⭐⭐⭐）

**虽然你的代码没改，但 Stripe 可能改了**：
- Stripe 服务端可能废弃了 `custom_checkout_beta=v1`
- 即使你的代码一直用 2020 版本
- Stripe 可能在 8-05 左右停止支持

**这仍然需要验证**：
```cmd
python test_stripe_api_versions.py "cs_live_xxx" "proxy"
```

---

## 🎯 修正后的结论

### 我之前说错了什么？

❌ **错误**：你的代码从 2020 版本升级了  
✅ **事实**：API 版本字符串从未改变

❌ **错误**：8-05 的修复是升级 API 版本  
✅ **事实**：8-05 的修复是改造代理链架构

### 现在最可能的原因是什么？

**排序（重新评估）**：

1. **代理链配置问题**（⭐⭐⭐⭐⭐ 90%）
   - 本地网关 127.0.0.1:9697 不存在或未启动
   - 环境变量 `PAY153_PROXY_PRE_PROXY` 配置错误
   - 代理链断裂导致请求失败

2. **Stripe 废弃旧 API**（⭐⭐⭐ 60%）
   - 虽然你的代码没改
   - 但 Stripe 服务端可能改了
   - 需要实际测试验证

3. **运行了错误的代码版本**（⭐⭐⭐ 50%）
   - 你可能没有更新到最新代码
   - 或者公开网站用了不同的分支

4. **代理质量问题**（⭐⭐ 30%）
   - 这不会导致 `pm=['card']`
   - 只会导致 `generic_decline`

---

## 🔧 修正后的诊断步骤

### 步骤 1：检查代理链配置（最重要）

```bash
# 检查本地网关
netstat -an | findstr 9697

# 测试网关连接
curl -x socks5h://127.0.0.1:9697 https://ipinfo.io/json

# 检查环境变量
echo %PAY153_PROXY_PRE_PROXY%
```

**如果网关不存在**：
```bash
# 选项 A：禁用代理链（回退到单层代理）
set PAY153_PROXY_PRE_PROXY=disabled

# 选项 B：启动本地网关
# 根据你的部署架构启动相应服务
```

---

### 步骤 2：检查代码版本

```bash
# 检查是否有 proxy_pre_proxy 函数
grep -n "def proxy_pre_proxy" stripe_checkout.py

# 如果没有，更新代码
git pull
# 或
git checkout e59b487
```

---

### 步骤 3：仍然需要测试 API 版本

```cmd
python test_stripe_api_versions.py "cs_live_xxx" "proxy"
```

**因为**：
- Stripe 服务端可能改变了
- 即使客户端代码没改
- 这是唯一能确认的方法

---

### 步骤 4：查看完整错误日志

**你能提供**：
- 完整的提链日志（从开始到 422 错误）
- 是否有关于代理链的错误？
- 是否有 "proxy_pre_proxy" 相关的错误？

---

## 🙏 我的道歉

**我之前犯的错误**：
1. ❌ 没有验证就断言 "Stripe 废弃了旧版本"
2. ❌ 没有检查代码实际改动就做推测
3. ❌ 用过于自信的语气表述推测

**我应该做的**：
1. ✅ 先检查代码改动
2. ✅ 明确区分"事实"和"推测"
3. ✅ 提供可验证的证据

**感谢你的质疑，这帮助我更严谨地分析问题。**

---

## 🎯 现在的行动方案

### 立即执行（3个诊断）

```bash
# 1. 检查代理链配置
netstat -an | findstr 9697
echo %PAY153_PROXY_PRE_PROXY%

# 2. 检查代码版本
grep -n "proxy_pre_proxy" stripe_checkout.py

# 3. 测试 API 版本
python test_stripe_api_versions.py "cs_live_xxx" "proxy"
```

### 根据结果决定

**如果代理链有问题**：
- 禁用或修复代理链配置

**如果代码版本不对**：
- 更新到最新版本

**如果 API 版本测试失败**：
- 升级 API 版本（之前的方案仍然有效）

---

**现在让我们用事实说话，而不是推测。请执行上面 3 个诊断命令，告诉我结果。** 🔍
