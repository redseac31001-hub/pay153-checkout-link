# oaics_* 转换失败自动重试功能

## 改动概述

当 OpenAI Checkout 返回 `oaics_*`（OpenAI 内部 Session）且无法通过 `update_checkout_promo` 转换为 `cs_live_*`（Stripe Session）时，系统现在会**自动换用新的代理池重试整个流程**，而不是直接返回 `requires_browser: True`。

## 核心变更

### 1. 新增异常类（app.py:48-63）

```python
OAICS_CONVERSION_FAILED_ERROR_CODE = "oaics_conversion_failed_retry"
MAX_OAICS_RETRY = 2  # 最多重试2次，总共3次尝试

class OaicsConversionFailedError(RuntimeError):
    """当 oaics_* 无法转换为 cs_live_* 时抛出，触发外层重试逻辑。"""
    error_code = OAICS_CONVERSION_FAILED_ERROR_CODE
```

### 2. 修改转换失败逻辑（app.py:1498-1559）

**旧逻辑**：
- oaics 转换失败 → 直接设置 `openai_managed_checkout = True` → 返回 `requires_browser: True`

**新逻辑**：
- oaics 转换失败 → 检查重试次数
  - **未达上限**：抛出 `OaicsConversionFailedError`，触发外层重试
  - **已达上限**：回退到旧逻辑（返回 OpenAI 托管结账页）

```python
current_oaics_retry = options.get("_oaics_retry_count", 0)
if current_oaics_retry < MAX_OAICS_RETRY:
    raise OaicsConversionFailedError("需要重试")
else:
    # 重试耗尽，使用 OpenAI 托管结账页
    options["openai_managed_checkout"] = True
```

### 3. 外层重试捕获（app.py:1248-1263）

在 `_run` 方法中捕获 `OaicsConversionFailedError`：
- 递增 `options["_oaics_retry_count"]`
- 自动换用新代理池
- 重新创建 Checkout Session
- **不计入** `max_attempts` 限制

```python
if error_code == OAICS_CONVERSION_FAILED_ERROR_CODE:
    current_oaics_retry = current.get("_oaics_retry_count", 0)
    current["_oaics_retry_count"] = current_oaics_retry + 1
    self.log(job_id, f"[oaics 重试 {current_oaics_retry + 1}/{MAX_OAICS_RETRY}] 换用新代理池")
    time.sleep(1.5)
    continue  # 直接重试，不计入 max_attempts
```

### 4. 结果中记录重试信息（app.py:1589-1592）

```python
result: dict[str, Any] = {
    # ... 其他字段
    "oaics_retry_count": options.get("_oaics_retry_count", 0),
    "oaics_retry_success": bool(
        options.get("_oaics_retry_count", 0) > 0 and is_stripe_checkout_session_id(session_id)
    ),
}
```

## 行为变化

### 场景1：第1次就返回 cs_live_*
- **行为**：正常流程，无变化
- **result**: `oaics_retry_count=0, oaics_retry_success=false`

### 场景2：第1次返回 oaics_*，转换成功
- **行为**：通过 `update_checkout_promo` 转换为 cs_live_*，继续 Stripe 流程
- **result**: `oaics_retry_count=0, oaics_retry_success=false`

### 场景3：第1次返回 oaics_*，转换失败，第2次返回 cs_live_*
- **旧行为**：返回 `requires_browser: True`，用户手动完成
- **新行为**：
  1. 自动换代理重试
  2. 第2次创建 Checkout 成功返回 cs_live_*
  3. 继续 Stripe 流程
- **result**: `oaics_retry_count=1, oaics_retry_success=true`

### 场景4：3次都返回 oaics_* 且转换失败
- **行为**：
  1. 自动重试2次（共3次尝试）
  2. 重试耗尽后，返回 OpenAI 托管结账页
  3. 返回 `requires_browser: True`
- **result**: `oaics_retry_count=2, oaics_retry_success=false, requires_browser=true`

## 日志输出示例

### 成功重试（第2次转换成功）
```
[checkout] Checkout 返回 OpenAI 内部 Session oaics_abc123...，先更新优惠并识别后续 Checkout 协议
[promo] checkout/update: 200; success=True
[checkout] oaics_* 转换失败（第 1 次尝试），将自动重试新流程（剩余 2 次）
========== 提链尝试 1/3 ==========
[oaics 重试 1/2] 换用新代理池重新创建 Checkout
[checkout] Checkout 返回 Stripe Session cs_live_xyz789...，后续 Stripe 请求使用该 ID
```

### 重试耗尽（3次都失败）
```
[checkout] oaics_* 转换失败（第 1 次尝试），将自动重试新流程（剩余 2 次）
[oaics 重试 1/2] 换用新代理池重新创建 Checkout
[checkout] oaics_* 转换失败（第 2 次尝试），将自动重试新流程（剩余 1 次）
[oaics 重试 2/2] 换用新代理池重新创建 Checkout
[checkout] oaics_* 转换失败且已重试 2 次，切换为 OpenAI 托管结账页，需要浏览器完成
[checkout] 当前为 OpenAI 托管 oaics_* Checkout；已切换官方结账页，不再调用 Stripe payment_page
```

## 测试覆盖

### 单元测试（tests/test_checkout_session_ids.py）
- `test_oaics_conversion_failed_error_is_retryable`：验证异常 error_code
- `test_max_oaics_retry_constant`：验证 MAX_OAICS_RETRY 常量
- `test_oaics_retry_count_in_options`：验证 options 中的重试计数器

### 集成测试（tests/test_oaics_retry_integration.py）
- 异常类定义验证
- 常量定义验证
- 代码结构验证

## 性能影响

- **额外延迟**：每次重试增加约 10-20 秒（创建新 Checkout + 代理切换）
- **最坏情况**：3次都失败，总延迟约 30-60 秒
- **成功案例**：第2次成功，额外延迟约 10-20 秒，但避免了用户手动操作

## 配置项

可通过修改 `MAX_OAICS_RETRY` 调整重试次数：
- **默认值**: 2（总共3次尝试）
- **建议范围**: 1-3
- **权衡**：次数越多，成功率越高，但延迟也越大

## 兼容性

- ✅ **向后兼容**：旧的 `requires_browser` 逻辑保留为最终回退方案
- ✅ **不影响现有流程**：只在 oaics 转换失败时触发
- ✅ **不计入 max_attempts**：oaics 重试独立计数，不影响现有重试逻辑

## 未来优化方向

1. **智能代理选择**：记录哪些代理返回过 oaics_*，下次优先避开
2. **动态重试次数**：根据 provider 类型调整（如 paypal 多重试）
3. **部分状态保留**：重试时复用 device_id、did，减少重新生成开销
4. **重试间隔优化**：当前固定 1.5 秒，可改为渐进式延迟（1s, 2s, 3s）
