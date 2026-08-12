# PAY.153 Checkout Link Router

<p align="center">
  <strong>多支付通道提链控制台。</strong><br>
  Hosted、PayPal、iDEAL、UPI、PIX、Team 与 Codex 空间方案统一任务化处理。
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white">
  <img alt="Flask" src="https://img.shields.io/badge/Backend-Flask-000000?logo=flask&logoColor=white">
  <img alt="curl_cffi" src="https://img.shields.io/badge/HTTP-curl__cffi-0EA5E9">
  <img alt="Repository" src="https://img.shields.io/badge/Repository-Private-111827">
</p>

## 页面预览

### 桌面端

![桌面端页面](docs/screenshots/desktop.png)

### 手机端

<p align="center">
  <img src="docs/screenshots/mobile.png" alt="手机端页面" width="390">
</p>

## 功能概览

- 支持 Plus、Pro、Team 与 Codex 低价空间等计划参数。
- 支持 Hosted 官方长链、PayPal、iDEAL、UPI、PIX 和 Gopay 支付路径。
- 支持 Access Token 和 Session JSON 自动识别。
- 双代理池、1–500 条代理、本地保存、代理检测和地区自适应。
- 代理池支持默认共享与按支付方式独立记忆，切换方式时自动恢复对应配置。
- Gopay 支持按 `gopay:ID` 保存本地账单地址档案；档案不完整或国家不一致时会在提交前阻止任务。
- 按支付地区自动选择币种，并处理不受支持币种的回退逻辑。
- 支持优惠更新、金额重新校验与零元账单判断。
- 支持失败重试，每轮重建 Checkout、设备标识和支付参数。
- 提供全局 RPM、单 IP RPM、并发限制和任务排队。
- 支持停止任务、进度展示、精简前端日志和完整后台日志。
- 支持支付二维码、跳转链接、倒计时和结果复制。
- 深色/浅色主题，以及桌面端和手机端响应式布局。
- 提供受密码保护的 `/manage` 管理中心，维护代理池、账单档案、国家 ASN、成功节点和日志。

## 支付路径

| 路径 | 用途 |
|---|---|
| Hosted | 返回官方 Checkout 长链 |
| PayPal | 创建 PayPal PaymentMethod 并返回 Approve 跳转 |
| iDEAL | 荷兰银行支付路径 |
| UPI | 印度 UPI 支付与二维码 |
| PIX | 巴西 PIX 支付与二维码 |
| Gopay | 印尼电子钱包支付 |

## 项目结构

```text
pay153-checkout-link/
├─ app.py                       # Flask API、任务队列、限流与入口
├─ manage_store.py              # SQLite 管理存储、加密与脱敏
├─ manage_defaults.py           # 国家 ASN 推荐默认值
├─ provider_checkout.py         # Checkout、地区、账单与支付提供商流程
├─ stripe_checkout.py           # Stripe 初始化、金额、确认与跳转处理
├─ billing_address_resolver.py  # 在线地图及账单地址解析
├─ sentinel_token.py            # Sentinel Token 生成与请求封装
├─ sentinel_sdk_full.js         # Sentinel SDK/VM 辅助代码
├─ gen_token_jsdom.js           # Node/JSDOM Token 辅助脚本
├─ package.json                 # Sentinel Node 运行依赖
├─ package-lock.json
├─ start-pay153.cmd             # Windows 启动/重启/停止脚本
├─ static/
│  ├─ index.html                # 提链控制台
│  ├─ app.js                    # 前端任务与交互逻辑
│  ├─ manage.html               # 管理中心
│  ├─ manage.js                 # 管理中心交互
│  ├─ manage.css                # 管理中心样式
│  └─ styles.css                # 主界面样式
├─ docs/screenshots/            # README 截图
├─ requirements.txt
└─ .env.example
```

## 快速启动

```bash
git clone https://github.com/1537271403/pay153-checkout-link.git
cd pay153-checkout-link

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
npm install

python app.py
```

Windows 可使用项目自带脚本启动；`start` 和 `restart` 会先清理占用 `18082` 端口的旧进程：

```bat
start-pay153.cmd start
start-pay153.cmd restart
start-pay153.cmd stop
```

生产环境推荐使用 Gunicorn：

```bash
gunicorn --workers 1 --threads 12 --timeout 600 \
  --bind 127.0.0.1:18096 app:app
```

## 环境变量

复制示例文件：

```bash
cp .env.example .env
```

| 变量 | 作用 |
|---|---|
| `GOOGLE_MAPS_API_KEY` | 在线地图地址解析密钥，可选 |
| `PAY153_BILLING_ADDRESS_CACHE` | 地址缓存文件路径 |
| `PAY153_WORKERS` | 后台任务并发数 |
| `PAY153_GLOBAL_RPM` | 全局每分钟创建任务上限 |
| `PAY153_IP_RPM` | 单 IP 每分钟任务上限 |
| `PAY153_LOG_DIR` | 完整后台日志目录 |
| `PAY153_LEGACY_BASE` | 旧服务兼容地址，可选 |
| `PAY153_PROXY_PRE_PROXY` | 代理池 SOCKS 前置代理，默认 `socks5://127.0.0.1:9697`；留空可关闭 |
| `PAYPAL_APPROVE_POLL_ATTEMPTS` | PayPal 审批后等待跳转地址的轮询次数，默认 6，范围 1-12 |
| `PAY153_OAICS_PUBLISHABLE_KEY` | OAICS 未返回 publishable key 时的可选 Stripe 公钥 |
| `PAY153_OAICS_CONFIRM_AUTH` | OAICS 接口是否附带当前账号 Bearer，默认 `1`；设为 `0` 仅用于复现旧 HAR |
| `PAY153_OAI_CLIENT_VERSION` / `PAY153_OAI_CLIENT_BUILD_NUMBER` | ChatGPT Checkout 上下文版本头，可按当前页面更新 |
| `PAY153_OAI_WEB_DEPLOYMENT_ATTESTATION` | 可选的当前页面部署证明；过期值不要复用 |
| `PAY153_OAI_TELEMETRY` / `PAY153_OAI_CLIENT_OBSERVATION` | 可选运行时诊断头；留空时不发送 |
| `PAY153_OAICS_USER_AGENT` | OAICS 请求专用 User-Agent；为空时复用项目浏览器指纹 |
| `PAY153_OAICS_HCAPTCHA_TOKEN` | 可选的当前有效 hCaptcha token；动态一次性值，不能复用旧 HAR |
| `PAY153_STRIPE_JS_VERSION` | OAICS confirmation token 的 Stripe.js 版本，默认 `4dae3e22af` |
| `PAY153_OAICS_TIME_ON_PAGE` | OAICS confirmation token 的页面停留时间字段，默认 `42000` |
| `PAY153_MANAGE_PASSWORD` | 管理中心密码；为空时 `/manage` 的管理 API 保持关闭 |
| `PAY153_SESSION_SECRET` | Flask 登录会话密钥，生产环境建议固定设置 |
| `PAY153_MANAGE_ENCRYPTION_KEY` | 管理数据库的 Fernet 密钥；为空时自动生成本地密钥文件 |
| `PAY153_MANAGE_DB` | 管理数据库路径，默认 `data/pay153_manage.sqlite3` |
| `PAY153_MANAGE_KEY_FILE` | 自动生成的 Fernet 密钥路径，默认 `data/.manage.key` |

## 代理池

每行一条代理，支持常见格式：

```text
host:port:username:password
http://username:password@host:port
https://username:password@host:port
socks5://username:password@host:port
```

任务提交后会根据支付路径和地区选择代理；代理凭据仅应通过网页或环境变量传入。

当前国家/地区的 ASN 推荐顺序会保存到浏览器本地键 `pay153.proxy_asn_recommendations.v1`，用于选择参考；它不会自动修改或重排代理池里的实际 IP。

代理池采用两跳链路：本地 SOCKS5 `PAY153_PROXY_PRE_PROXY` 是第一跳，代理池中的每条代理是最终出口。程序通过 curl 的 `PRE_PROXY` 建立到代理池节点的连接，因此不会把本地 9697 误当成地区出口。9697 必须支持 SOCKS5 并允许连接到代理池节点；如果本地代理服务不可用，所有代理池检测都会失败。设置 `PAY153_PROXY_PRE_PROXY=` 可恢复代理池直连。

OAICS PayPal 使用本地 HTTP 接口链路，不依赖浏览器：读取 OAICS 状态、提交 `checkout/taxes`，初始化 Stripe Elements Session，向 Stripe `v1/confirmation_tokens` 创建 `ctoken_*`，再向 OpenAI `payments/checkout/confirm` 提交；若 confirm 返回 `pi_*`/`seti_*` client secret，会继续确认对应 Intent 并解析 PayPal 跳转。所有步骤复用当前支付会话和代理链，因此仍经过 9697。优惠任务会先核验应付金额为 0；`blocked`、401、缺少 BA 或动态验证码失败会进入 OAICS 专用重试，耗尽后回退官方 OAICS 结账页。hCaptcha、部署证明等动态字段不会伪造或复用旧 HAR token。

## 管理中心

设置 `PAY153_MANAGE_PASSWORD` 后访问 `/manage`。管理中心仍和当前 Flask 服务放在一起，数据落到本地 SQLite，不额外拆分服务：

- **代理池**：按支付方式、国家和入口/支付出口用途维护，Gopay 保持两池模型；
- **账单档案**：维护 `支付方式:国家` 档案，例如 `gopay:ID`；
- **国家 / ASN**：保存地区推荐顺序，仅作为参考，不会自动重排实际代理；
- **成功节点**：记录任务成功后的账号哈希、地区、入口/支付出口 IP 和任务信息；
- **任务日志**：按日期、Job ID 和关键词查看已脱敏日志。

工作台的代理、账单和 ASN 配置仍保存在浏览器 localStorage。管理中心不会自动上传这些数据，只有点击“导入浏览器配置”并确认后才会写入本地数据库。Token 不在导入范围内；代理凭据、账单字段和成功链接在管理库中使用 Fernet 加密，列表默认脱敏。`data/.manage.key` 或自定义 `PAY153_MANAGE_ENCRYPTION_KEY` 必须像密码一样保管。

## 生产部署

systemd 示例：

```ini
[Unit]
Description=PAY.153 Checkout Link Service
After=network-online.target

[Service]
WorkingDirectory=/opt/pay153
EnvironmentFile=-/opt/pay153/.env
Environment=PAY153_WORKERS=20
Environment=PAY153_GLOBAL_RPM=20
Environment=PAY153_IP_RPM=3
ExecStart=/opt/pay153/.venv/bin/gunicorn --workers 1 --threads 12 --timeout 600 --bind 127.0.0.1:18096 app:app
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```

Nginx 将域名请求反向代理至：

```text
http://127.0.0.1:18096
```

## 数据与密钥

仓库未包含以下生产数据：

- `.env` 与真实管理令牌
- 代理账号和密码
- Access Token、Session JSON 与账号池
- 任务结果、日志、截图缓存和历史备份
- `data/`、`logs/`、`backups/` 与虚拟环境

提交代码前应继续检查环境变量、调试输出和测试文件，避免将运行凭据写入 Git 历史。

## 与协议支付项目的关系

本仓库负责生成支付链接或二维码；PayPal BA 链生成后，可以交给独立的协议支付服务继续处理：

https://github.com/1537271403/paypal-agreement-protocol

## 更新流程

```bash
git pull
python -m pip install -r requirements.txt
sudo systemctl restart pay153
```

检查服务：

```bash
systemctl status pay153
curl http://127.0.0.1:18096/api/health
```
