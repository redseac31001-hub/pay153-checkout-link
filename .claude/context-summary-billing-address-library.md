## 项目上下文摘要（账单地址库完善）

生成时间：2026-08-10 12:00:00

### 1. 相似实现分析
- **billing_address_resolver.py**: 核心地址解析器，提供内置公共地址、Google Places、Nominatim（OpenStreetMap）三种来源，支持BA/US/GB，带有缓存和随机挑选逻辑。
- **tests/test_billing_profiles.py**: 测试 normalize_billing_profile 和 default_billing，验证国家绑定和手动地址覆盖。
- **tests/test_billing_profile_ui.py**: 浏览器模拟测试 Gopay/PayPal 账单块显示和保存/恢复。

### 2. 项目约定
- 命名：billing_address_resolver.py、billing_profiles、default_billing。
- 代码风格：Python 3.9+，类型提示严格，注释用中文，UTF-8，无 BOM。
- 文件组织：app.py 为主入口，tests/ 包含单元和 UI 测试。

### 3. 可复用组件清单
- billing_address_resolver.py 中的 resolve_public_address 函数（可复用地址解析）。
- provider_checkout.py 中的 default_billing 和 normalize_billing_profile（地址规范化）。
- manage_store.py 中的缓存机制（可复用到其他模块）。

### 4. 测试策略
- 框架：unittest + Node.js JSDOM UI 测试。
- 覆盖：正常流程（Gopay ID/TH）、边界（国家不匹配）、错误恢复。
- 参考：tests/test_billing_profiles.py 和 test_billing_profile_ui.py。

### 5. 依赖和集成点
- 外部：curl_cffi (requests)、json、threading、pathlib。
- 内部：provider_checkout.default_billing、manage_store 缓存。
- 集成：通过 app.py 中的 default_billing 调用 resolve_public_address。

### 6. 技术选型理由
- 为什么用内置+API：避免依赖外部服务，快速 fallback 到公共酒店地址，提升支付成功率。
- 优势：低延迟、隐私好、可配置缓存。
- 劣势：需定期更新内置地址（可通过管理后台完善）。

### 7. 关键风险点
- 并发：使用 RLock 保护缓存。
- 边界：国家代码大小写、缺少邮编时 fallback。
- 性能：Nominatim 限速，使用全局锁。
- 安全：无敏感数据，仅公开地址。

### 8. 完善方向
- 增加更多国家到 _BUILTIN_PUBLIC_ADDRESSES（ID, TH, MY 等）。
- 增强 _pick 逻辑，支持 preferred_city 优先。
- 添加更多来源（如本地 CSV）。
- 完善错误处理和日志。
- 增加单元测试覆盖率到 90%+。

### 9. 交付物
- 修改 billing_address_resolver.py（新增地址和优化逻辑）。
- 更新 tests/test_billing_profiles.py 和 UI 测试。
- 生成 .claude/verification-report.md。
- 更新 README.md 或 operations-log.md。