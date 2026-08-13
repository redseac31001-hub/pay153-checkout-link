# 代理地区检测失败问题诊断

**时间：** 2026-08-10 02:19  
**问题：** 10 次提链尝试全部失败，错误信息 `RuntimeError: 代理地区检测失败：ProxyError / ProxyError / ProxyError`

---

## 🔍 问题分析

### 错误信息
```
代理链：SOCKS5 本地第一跳已启用（PAY153_PROXY_PRE_PROXY），代理池条目作为最终出口
错误：RuntimeError: 代理地区检测失败：ProxyError / ProxyError / ProxyError
```

### 错误来源

**文件：** `app.py:854-887` - `proxy_geo()` 函数

```python
def proxy_geo(proxy: str) -> dict[str, str]:
    http = sc.build_http(proxy)  # ← 使用双层代理
    probes = (
        "https://ipapi.co/json/",        # ← 探测接口 1
        "http://ip-api.com/json/...",    # ← 探测接口 2
        "https://ipinfo.io/json",        # ← 探测接口 3
    )
    errors: list[str] = []
    for url in probes:
        try:
            resp = http.get(url, timeout=20)
            # ... 解析响应
        except Exception as exc:
            errors.append(type(exc).__name__)  # ← 记录异常类型
    
    # 所有探测都失败 → 抛出错误
    raise RuntimeError(f"代理地区检测失败：{' / '.join(errors[-3:])}")
```

---

## ✅ 诊断结果

### 1. 本地网关（127.0.0.1:9697）可用

**测试命令：**
```bash
curl -x socks5h://127.0.0.1:9697 http://ip-api.com/json/...
```

**结果：**
```json
{"status":"success","countryCode":"JP","query":"35.77.108.176"}
```

**结论：** ✅ 本地 SOCKS5 网关正常运行，可以访问外网

---

### 2. ipinfo.io 接口限流

**测试命令：**
```bash
curl -x socks5h://127.0.0.1:9697 https://ipinfo.io/json
```

**结果：**
```json
{
  "status": 429,
  "error": {
    "title": "Rate limit hit",
    "message": "Sign up at ipinfo.io"
  }
}
```

**结论：** ⚠️ ipinfo.io 触发限流（HTTP 429），但这只是 3 个探测接口之一

---

### 3. **根本原因：代理池条目不可达**

**错误特征：**
- 3 个探测接口**全部抛出 `ProxyError`**
- 错误信息没有 `HTTP 429` 或 `HTTP 4xx`，而是纯粹的 `ProxyError`

**可能的原因：**

#### A. 代理池条目格式错误

**示例：**
```python
# 错误格式
proxy = "http://user:pass@host:port"  # ← 代理池是 SOCKS5，不是 HTTP

# 正确格式
proxy = "socks5://user:pass@host:port"
```

#### B. 代理池凭据失效

**示例：**
```python
# 商业代理凭据过期
proxy = "socks5://expired_user:old_pass@proxy.example.com:1080"
```

#### C. 代理池条目无法通过本地网关访问

**场景：**
- 本地网关（127.0.0.1:9697）是日本节点
- 代理池条目是内网地址或需要特定路由
- 双层代理链路不通

#### D. 代理池条目本身已失效

**示例：**
```python
# VPS 已下线或 IP 被封禁
proxy = "socks5://user:pass@dead-host.example.com:1080"
```

---

## 🔧 诊断步骤

### 步骤 1：检查代理池条目格式

**查看代理池配置：**
```bash
# 假设代理池存储在某个配置文件或数据库中
# 你需要告诉我代理池条目的来源
```

**预期格式：**
```python
# 代理池 1（入口/优惠）
proxy_pool_1 = [
    "socks5://user:pass@entry1.example.com:1080",
    "socks5://user:pass@entry2.example.com:1080",
    # ...
]

# 代理池 2（支付出口）
proxy_pool_2 = [
    "socks5://user:pass@exit1.example.com:1080",
    "socks5://user:pass@exit2.example.com:1080",
    # ...
]
```

---

### 步骤 2：手动测试代理池条目

**测试命令模板：**
```bash
# 替换为真实的代理池条目
PROXY="socks5://your_user:your_pass@your_host:your_port"

# 测试单层代理（不经过本地网关）
curl -x "$PROXY" http://ip-api.com/json/?fields=countryCode,query --connect-timeout 10

# 测试双层代理（经过本地网关）
# 注意：curl 不支持 PRE_PROXY，需要用 Python 测试
```

**Python 测试脚本：**
```python
from curl_cffi.requests import Session
from curl_cffi import CurlOpt

# 替换为真实的代理池条目
proxy = "socks5://your_user:your_pass@your_host:your_port"

# 双层代理配置
http = Session(
    impersonate='chrome136',
    curl_options={CurlOpt.PRE_PROXY: 'socks5h://127.0.0.1:9697'}
)
http.proxies = {'http': proxy, 'https': proxy}

# 测试
try:
    resp = http.get('http://ip-api.com/json/?fields=countryCode,query', timeout=10)
    print('Success:', resp.text)
except Exception as e:
    print('Error:', type(e).__name__, str(e))
```

---

### 步骤 3：检查代理池凭据有效性

**如果代理池是商业服务：**
- 登录商业代理服务商后台
- 检查账户余额是否充足
- 检查凭据是否过期
- 检查 IP 白名单是否正确

**如果代理池是自建 VPS：**
- SSH 登录 VPS 检查代理服务是否运行
- 检查防火墙规则是否允许本地网关访问
- 检查代理服务日志是否有连接拒绝记录

---

### 步骤 4：简化测试（关闭双层代理）

**临时关闭本地网关，测试代理池是否可直连：**

```bash
# .env
PAY153_PROXY_PRE_PROXY=  # 留空，关闭双层代理
```

**重启应用并测试：**
```bash
taskkill /F /IM python.exe
python app.py
```

**预期结果：**
- ✅ 如果成功 → 问题在双层代理链路（本地网关无法访问代理池）
- ❌ 如果仍失败 → 问题在代理池条目本身（失效/格式错误）

---

## 🎯 快速修复方案

### 方案 1：如果代理池可直连

**关闭双层代理：**
```bash
# .env
PAY153_PROXY_PRE_PROXY=
```

**优点：** 减少一跳延迟，提高成功率  
**缺点：** 无法利用本地网关的路由优势

---

### 方案 2：如果代理池凭据失效

**更新代理池凭据：**
```python
# 你需要告诉我代理池配置在哪里
# 我可以帮你批量更新凭据
```

---

### 方案 3：如果代理池条目全部失效

**更换代理池：**
- 使用新的商业代理服务（Bright Data、Oxylabs、IPRoyal）
- 重新部署自建代理节点
- 临时使用免费代理池（不推荐，质量差）

---

## 📊 日志分析

### 正常的代理检测日志（Gopay 成功案例）

```
代理链：SOCKS5 本地第一跳已启用（PAY153_PROXY_PRE_PROXY），代理池条目作为最终出口
[stripe] 代理地区检测：country=ID city=Jakarta ip=103.x.x.x
[gopay] 第 3/7 步：Stripe init
...
```

### 异常的代理检测日志（当前 PayPal 失败）

```
代理链：SOCKS5 本地第一跳已启用（PAY153_PROXY_PRE_PROXY），代理池条目作为最终出口
错误：RuntimeError: 代理地区检测失败：ProxyError / ProxyError / ProxyError
```

**差异：**
- Gopay 成功：代理检测通过，拿到 country/city/ip
- PayPal 失败：代理检测 3 次全部 ProxyError

---

## ❓ 需要你提供的信息

### 1. 代理池条目来源

**请告诉我：**
- 代理池是商业服务还是自建？
- 代理池配置文件路径？（如 `proxy_pool.json`、数据库表名等）
- 代理池条目示例？（脱敏后，如 `socks5://user:***@example.com:1080`）

### 2. Gopay 成功时的配置

**关键问题：**
- Gopay 测试成功时，`PAY153_PROXY_PRE_PROXY` 是启用还是关闭的？
- Gopay 使用的代理池条目是哪个？（代理池 1 还是代理池 2？）

### 3. 最近的配置变更

**是否有以下操作：**
- 更换了商业代理服务商？
- 重启了本地网关（127.0.0.1:9697）？
- 修改了代理池条目？

---

## 🚀 立即行动

### 临时方案：关闭双层代理测试

```bash
# 1. 编辑 .env
PAY153_PROXY_PRE_PROXY=

# 2. 重启应用
taskkill /F /IM python.exe
python app.py

# 3. 重新测试 PayPal 提链
```

**如果成功 → 问题在双层代理链路**  
**如果仍失败 → 问题在代理池条目本身**

---

**请先尝试临时方案，然后告诉我结果和上述 3 个问题的答案，我会给出精确的修复方案！** 🎯
