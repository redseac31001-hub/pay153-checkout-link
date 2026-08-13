# Gopay 快速参考

## 使用方式

- 支付方式：选择 **Gopay**。
- 代理池 1：推荐 TH，用于资格识别和优惠更新。
- 代理池 2：推荐 ID，用于创建 ID/IDR Checkout 和完成支付。
- 不需要填写额外的泰国代理池。

切换其他支付方式时，当前代理池会自动保存；该方式如果有专属配置就恢复专属配置，否则继承默认共享配置。

## 预期日志

```text
代理池 1（优惠更新）共 X 条，代理池 2（印尼支付）共 Y 条
Gopay 代理校验：优惠更新=TH/地区，支付 Checkout=ID/地区，账单=ID/IDR
第 2/7 步：使用印尼 IP 创建 Gopay Checkout（稍后通过代理池 1 更新优惠）
Gopay 设置：代理池 1（TH）仅用于优惠更新，代理池 2（ID）创建 ID/IDR Checkout 并贯穿 Stripe 支付处理
Gopay 已确认可用，正在通过代理池 1 提交优惠
Gopay 提取完成
```

## 技术流程

1. 代理池 1 预检活动并调用通用 `checkout/update`。
2. 代理池 2 创建 Checkout、初始化 Stripe、创建 Gopay PaymentMethod 并 approval。
3. 任务重试时由通用双池组合轮换代理。

## 验证

```bash
python test_gopay_integration.py
python -m py_compile app.py provider_checkout.py test_gopay_integration.py
```
