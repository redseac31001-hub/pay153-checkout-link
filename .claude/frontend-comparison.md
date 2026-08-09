# 前端代码对比分析：docs/app.js vs static/app.js

## 📊 主要差异总结

| 特性 | docs/app.js（公开网站） | static/app.js（你的本地） |
|------|----------------------|------------------------|
| **代码行数** | 324 行 | 327 行 |
| **支持的支付方式** | 6 种 | 5 种 |
| **代理检测功能** | ❌ 无 | ✅ 有 |
| **私有模式支持** | ✅ 有 | ❌ 无 |
| **轮询间隔** | 3000ms | 1200ms |
| **队列位置提示** | ✅ 有 | ✅ 有 |

---

## 🔍 详细差异对比

### 差异 1：支持的支付方式（重要）

**docs/app.js（公开网站）- 第 20-26 行**：
```javascript
const providerDefaults = {
  hosted: {country: 'US', currency: 'USD'}, 
  paypal: {country: 'US', currency: 'USD'},
  ideal: {country: 'NL', currency: 'EUR'}, 
  upi: {country: 'IN', currency: 'INR'},
  pix: {country: 'BR', currency: 'BRL'}, 
  momo: {country: 'VN', currency: 'VND'},    // ✅ 多了 momo
  gcash: {country: 'PH', currency: 'PHP'},   // ✅ 多了 gcash
  kakao: {country: 'KR', currency: 'KRW'}    // ✅ 多了 kakao
};
```

**static/app.js（你的本地）- 第 20-24 行**：
```javascript
const providerDefaults = {
  hosted: {country: 'US', currency: 'USD'}, 
  paypal: {country: 'US', currency: 'USD'},
  ideal: {country: 'NL', currency: 'EUR'}, 
  upi: {country: 'IN', currency: 'INR'},
  pix: {country: 'BR', currency: 'BRL'}
  // ❌ 没有 momo、gcash、kakao
};
```

**结论**：公开网站支持更多支付方式（momo/gcash/kakao），但这**不影响 PayPal 功能**。

---

### 差异 2：代理检测功能（重要）

**static/app.js（你的本地）- 第 37-70 行**：
```javascript
// ✅ 有代理检测功能
function setProxyProbeResult(node, text, state=''){...}
async function probeProxyPool(inputId, buttonId, resultId, poolLabel){
  // 调用 /api/proxy-probe 检测代理
  const response = await fetch('/api/proxy-probe', {...});
  ...
}

// 绑定检测按钮
$('probeEntryProxy').addEventListener('click', () => probeProxyPool(...));
$('probeExitProxy').addEventListener('click', () => probeProxyPool(...));
```

**docs/app.js（公开网站）- 没有这部分代码**：
```javascript
// ❌ 没有代理检测功能
// 直接从第 71 行开始 setProxySaveState
```

**结论**：你的本地版本**增强了代理检测功能**，这是好事！但公开网站没有这个功能。

---

### 差异 3：轮询间隔（可能影响性能）

**docs/app.js（公开网站）- 第 299 行**：
```javascript
pollTimer=setInterval(poll,3000);  // ✅ 3秒轮询一次
```

**static/app.js（你的本地）- 第 299 行**：
```javascript
pollTimer=setInterval(poll,1200);  // ⚡ 1.2秒轮询一次（更快）
```

**结论**：你的本地版本轮询更频繁（1.2秒 vs 3秒），这可能导致：
- ✅ 更快获取结果
- ❌ 更多服务器压力

---

### 差异 4：私有模式支持

**docs/app.js（公开网站）- 第 3、308-319 行**：
```javascript
// 第 3 行
const privateMode = location.pathname.replace(/\/+$/, '') === '/private-checkout';

// 第 308-319 行
if (privateMode) {
  document.body.classList.add('private-mode');
  document.title = 'PAY.153 · 私有直通提链';
  ...
  // 显示"私有直通通道"提示
  const limitNote = document.querySelector('.public-limit-note');
  if (limitNote) limitNote.innerHTML = '<b>私有直通通道</b>...';
}
```

**static/app.js（你的本地）**：
```javascript
// ❌ 没有 privateMode 相关代码
```

**结论**：公开网站有**私有直通模式**（独立执行池），你的本地版本没有。

---

### 差异 5：队列位置提示逻辑

**docs/app.js（公开网站）- 第 282-283 行**：
```javascript
if (data.internal) setProgress(4, '私有直通任务已进入独立执行池', 'running');
else if (data.queue_position > 0) setProgress(2, `任务已进入队列，当前第 ${data.queue_position} 位`, 'queued');
```

**static/app.js（你的本地）- 第 298 行**：
```javascript
if (data.queue_position > 0) setProgress(2, `任务已进入队列，当前第 ${data.queue_position} 位`, 'queued');
// ❌ 没有 data.internal 判断
```

**结论**：公开网站有**私有通道判断**，你的本地版本只有队列判断。

---

### 差异 6：支付方式提示文本

**docs/app.js（公开网站）- 第 98-107 行**：
```javascript
const recommendations = {
  hosted: 'Pool 2 creates Checkout; Pool 1 applies the promotion region update.',
  ph_short: 'Use the selected billing country for Checkout; use TR for promotion.',
  paypal: '推荐代理：...',
  ideal: '推荐代理：...',
  upi: '推荐代理：...',
  pix: '推荐代理：...',
  momo: '推荐代理：代理池 1 全程使用 VN...',
  gcash: '推荐代理：代理池 1 使用 US 创建 PH/PHP 账单...',
  kakao: '推荐代理：代理池 1 使用 VN 应用优惠...'
};
```

**static/app.js（你的本地）- 第 129-135 行**：
```javascript
const recommendations = {
  hosted: '推荐代理：使用账号常用地区。',
  paypal: '推荐代理：...',
  ideal: '推荐代理：...',
  upi: '推荐代理：...',
  pix: '推荐代理：...'
  // ❌ 没有 momo、gcash、kakao 的提示
};
```

---

### 差异 7：代理需求判断

**docs/app.js（公开网站）- 第 93 行**：
```javascript
const needsExit = rail !== 'pix' && rail !== 'momo';
```

**static/app.js（你的本地）- 第 124 行**：
```javascript
const needsExit = rail !== 'hosted' && rail !== 'pix';
```

**结论**：
- 公开网站：pix 和 momo 不需要 exit proxy
- 你的本地：hosted 和 pix 不需要 exit proxy

---

## 🎯 关键发现

### ✅ 好消息：前端代码差异**不影响 PayPal 422 错误**

**原因**：
1. ✅ 两个版本的 **PayPal 默认配置相同**（US/USD）
2. ✅ 两个版本的 **API 调用逻辑相同**（`/api/checkout`）
3. ✅ 两个版本的 **提交参数格式相同**
4. ✅ 422 错误发生在**后端 API**，不是前端代码

**所以 422 错误的根源仍然是后端的 Stripe API 版本问题！**

---

## 📊 功能对比总结

| 功能 | 公开网站 | 你的本地 | 优势方 |
|------|---------|---------|--------|
| **基础 PayPal 支持** | ✅ | ✅ | 相同 |
| **代理检测功能** | ❌ | ✅ | 本地 |
| **私有直通模式** | ✅ | ❌ | 公开 |
| **更多支付方式** | ✅ (8种) | ⚠️ (5种) | 公开 |
| **轮询频率** | 3秒 | 1.2秒 | 本地 |
| **代码可读性** | 相同 | 相同 | 相同 |

---

## 💡 结论与建议

### 1. 前端代码差异**不是** 422 错误的原因

**证据**：
- PayPal 相关逻辑完全相同
- API 调用方式相同
- 错误发生在后端返回的 `payment_method_types` 中

### 2. 422 错误的真正原因仍然是**后端 Stripe API 版本**

**你需要修复的是**：
- ✅ `stripe_checkout.py:37-40`（后端 Python 代码）
- ❌ 不是 `static/app.js`（前端 JavaScript 代码）

### 3. 你的本地前端代码**更好**

**优势**：
- ✅ 有代理检测功能（`/api/proxy-probe`）
- ✅ 轮询更快（1.2秒 vs 3秒）

### 4. 可选的前端升级

如果你想要公开网站的新功能，可以复制这些部分：

**新增 momo/gcash/kakao 支持**：
```javascript
// 复制 docs/app.js 的 providerDefaults（第 20-26 行）
// 复制 recommendations 中的 momo/gcash/kakao 部分（第 104-106 行）
```

**添加私有模式支持**：
```javascript
// 复制 docs/app.js 的 privateMode 相关代码（第 3、308-319 行）
```

---

## 🎯 最终建议

**立即执行**（解决 422 错误）：
```cmd
# 修复后端 API 版本（关键）
apply_stripe_fix.cmd

# 测试验证
python test_stripe_api_versions.py "cs_live_xxx" "proxy"
```

**可选升级**（增强功能）：
1. 复制 momo/gcash/kakao 支付方式支持
2. 添加私有直通模式
3. 调整轮询间隔为 3 秒（减少服务器压力）

**但这些都不影响 PayPal 422 错误的修复！关键仍然是后端 API 版本升级。** 🎯
