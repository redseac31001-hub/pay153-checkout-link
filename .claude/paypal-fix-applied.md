# PayPal 轮询超时修复记录

**修复时间：** 2026-08-11 01:45  
**问题：** PayPal approve 成功但轮询超时（30 秒不够）  
**根本原因：** PayPal 风控延迟响应 + 双层代理增加延迟

---

## ✅ 已完成的修复

### 1. 延长轮询超时（最关键）

**文件：** `.env`

**修改内容：**
```diff
- PAYPAL_APPROVE_POLL_ATTEMPTS=12  # 约 30 秒
+ PAYPAL_APPROVE_POLL_ATTEMPTS=20  # 约 50 秒
```

**效果：**
- 轮询时间从 30 秒延长到 50 秒
- 给 PayPal 服务端更多响应时间
- 预期将 6/10 的超时失败转为成功

---

### 2. 暂时关闭双层代理

**文件：** `.env`

**修改内容：**
```diff
- PAY153_PROXY_PRE_PROXY=socks5h://127.0.0.1:9697
+ PAY153_PROXY_PRE_PROXY=  # 留空，直接使用代理池出口
```

**理由：**
- 减少代理链路：本地→SOCKS5→代理池 改为 直接→代理池
- 降低网络延迟（减少一跳）
- 验证是否是双层代理导致的超时

---

## 🔄 需要手动操作

### 重启 Flask 应用（必须）

**原因：** `.env` 修改后需要重启应用才能生效

**方法 1：在当前终端**
```bash
# 终止旧进程
tasklist | grep python
taskkill /PID <进程ID> /F

# 重启应用
python app.py
```

**方法 2：在 Claude Code 中**
```bash
# 使用 ! 前缀在当前会话中运行
! taskkill /F /IM python.exe
! python app.py
```

---

## 📊 预期效果

### 修复前（当前状态）
```
10 次尝试中：
- 6 次：approve 成功但轮询超时（30 秒不够）
- 2 次：优惠码 invalid_promotion
- 1 次：GB 代理被判定不支持 PayPal
- 1 次：成功（被 invalid_promotion 中断）

成功率：≈ 0%
```

### 修复后（预期）
```
轮询超时延长到 50 秒
+ 关闭双层代理降低延迟
= 6/10 的超时失败转为成功

预期成功率：30-50%
```

---

## 🎯 下一步优化（待实现）

### 3. 添加冷却机制（代码实现）

**目标：** 连续失败 3 次后等待 5 分钟，避免触发风控

**实现位置：** `app.py` 任务重试循环

**伪代码：**
```python
failure_count = 0
for attempt in range(1, max_retries + 1):
    # 冷却检查
    if failure_count >= 3:
        self.log(job_id, "⏸️ 连续失败 3 次，冷却 5 分钟")
        time.sleep(300)
    
    try:
        result = do_checkout(...)
        failure_count = 0  # 成功后重置
        break
    except Exception as exc:
        failure_count += 1
        self.log(job_id, f"❌ 尝试 {attempt} 失败")
```

**预期效果：**
- 避免 10 分钟内连续 10 次失败
- 降低被 PayPal 风控的概率
- 成功率提升到 50-70%

---

### 4. 为 PayPal 添加补救机制（参考 Gopay）

**目标：** approve 后如果轮询超时，主动补交 SetupIntent

**参考代码：** `provider_checkout.py:1304-1340`

**关键差异：**
- Gopay：有 `confirm_local_setup_intent` 补救机制
- PayPal：只能被动轮询，拿不到结果就失败

**实现思路：**
```python
# stripe_checkout.py (PayPal 专用函数中)
def stripe_to_paypal_redirect(...):
    approve_callback(processor)
    
    # 轮询
    result = poll_payment_page_after_approve(...)
    
    # 新增：如果轮询超时，尝试补救
    if not result.get("redirect_url"):
        log("[paypal] 轮询超时，尝试直接补交 SetupIntent")
        result = confirm_local_setup_intent(
            http, pk, "paypal", result, payment_method_id, ctx, log
        )
```

**预期效果：**
- 即使轮询超时，也能通过补救机制拿到跳转链接
- 成功率提升到 70-90%

---

## 📚 相关文档

1. `.claude/paypal-vs-gopay-comparison.md` - 详细对比分析
2. `.claude/GOPAY_SUCCESS_NODE_LOGGING.md` - Gopay 成功案例
3. `.claude/paypal-generic-decline-analysis.md` - 问题诊断

---

## 🎊 总结

### 已修复（立即生效）
- ✅ 轮询超时延长到 50 秒
- ✅ 关闭双层代理降低延迟

### 待实现（需要代码修改）
- ⏳ 添加冷却机制（防止触发风控）
- ⏳ 添加补救机制（参考 Gopay 的成功经验）

### 下一步行动
1. **立即重启 Flask 应用**（让配置生效）
2. 测试 PayPal 链路（观察是否还超时）
3. 根据测试结果决定是否实现步骤 3-4

---

**记录完成时间：** 2026-08-11 01:45  
**修复优先级：** 🔴 高（步骤 1-2 已完成，等待重启生效）
