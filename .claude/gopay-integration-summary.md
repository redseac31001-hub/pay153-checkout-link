# Gopay 支付渠道说明

**更新时间：** 2026-08-10

## 代理池模型

Gopay 使用现有的两个代理池，不需要额外的泰国代理池字段：

| 代理池 | 用途 | 推荐地区 |
|---|---|---|
| 代理池 1 | 读取资格、提交优惠更新 | TH（泰国） |
| 代理池 2 | 创建 ID/IDR Checkout、Stripe 支付与 approval | ID（印度尼西亚） |

泰国线路只负责优惠更新，沿用 PayPal、UPI、iDEAL 等支付方式的通用 `checkout/update` 流程；Gopay 不在 Checkout 创建阶段原生携带优惠。

## 前端配置记忆

- 默认使用共享代理配置。
- 切换支付方式时，当前配置会自动保存，目标方式会恢复自己的配置。
- 首次使用某方式时继承默认配置；编辑后自动保存为该方式专属配置。
- 现有 `pay153.proxy_pool_1/2` 缓存会自动迁移到默认配置。
- 代理配置只保存在浏览器本地，不上传服务器。

## 流程

1. 代理池 1 预检账号活动。
2. 代理池 2 创建 ID/IDR Checkout，确认 `gopay` 可用。
3. 使用代理池 1 调用通用优惠更新接口。
4. 代理池 2 重新初始化 Stripe、校验金额、创建 PaymentMethod 并确认支付。
5. 通过代理池 2 approval 并提取支付链接。

## 代码约定

- `PROVIDER_DEFAULTS["gopay"]` 为 `ID/IDR`。
- Gopay 复用 `stripe_to_provider(..., provider="gopay")`。
- 前端只提交 `entry_proxies` 和 `exit_proxies`，不再提交 `th_proxies`。
- 失败重试由任务队列的通用代理池组合轮换处理。

## 验证

```bash
python test_gopay_integration.py
python -m py_compile app.py provider_checkout.py test_gopay_integration.py
```
