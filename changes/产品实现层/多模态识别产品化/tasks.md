# 多模态识别产品化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 按任务实施；每个任务完成后单独评审和验证。

**Goal:** 在复用现有 Facade、SemanticRecognitionService、缓存和语义证据层的前提下，构建具备 task-specific prompt、严格合同、局部 bbox、受控重试、attempt、成本、延迟、脱敏和离线合同测试的多模态识别执行层。

**Architecture:** 保持 `DrawingGraphToolFacade -> SemanticRecognitionService -> provider port` 主链，在 Service 与 provider 之间新增供应商无关、同步优先的执行流水线。`RecognitionRun` 与 `RecognitionAttempt` 保持图谱外；只有合同有效的 observation/interpretation 可按既有路径写图谱，relation evidence 只能是 candidate。

**Tech Stack:** Python、dataclasses/Enum、Pillow `>=10,<13`、httpx、unittest、现有 semantic cache/run log/payload store/repository。

## 全局约束

- 禁止无意义重构；只修改各任务明确列出的文件。
- 默认 `write_back=false`，dry-run 不持久化 run、attempt、payload、语义节点或关系。
- 不改变 Neo4j 来源事实 schema，不新增 RecognitionRun、RecognitionAttempt 或 PageInterpretation 图谱节点。
- provider 输出不是 source fact 或 deterministic derived fact；candidate 不得直接提升为 formal。
- 不新增 OCR、OpenCV、消息队列、后台 worker、产品级 HTTP/MCP/CLI adapter 或第二套 cache key。
- Qwen/DashScope 只是 provider adapter；task、crop、retry、cost、redaction 和写回逻辑不得进入 adapter。
- API key 只从环境读取，不进入 DTO、日志、payload、cache key、异常或测试 fixture。
- 单元/离线合同、live DashScope、黄金集、live Neo4j 和 Codex/MCP 验证必须分开报告。
- 每个任务遵循测试先行：先增加失败断言，确认失败，再做最小实现，最后运行该任务列出的独立测试。

## 任务总览

1. 执行状态与错误枚举合同
2. 执行策略与请求 DTO
3. Attempt、计量与执行结果 DTO
4. Task Registry 基础机制
5. page_summary task spec
6. element_text_observation task spec
7. block_semantic_identification task spec
8. basic_info_interpretation task spec
9. table_interpretation task spec
10. section_label_observation task spec
11. relation_evidence_extraction task spec
12. Task Registry 完整性校验
13. 目标身份与类型输入校验
14. bbox 与同页 context 输入校验
15. 输入安全字段与执行策略校验
16. 局部 bbox 内存裁剪
17. 图像方向、缩放与资源上限
18. task-specific prompt 渲染
19. JSON 与 task schema 输出校验
20. 目标归属与事实等级输出校验
21. Provider Port 与序列化 Fake
22. Qwen prepared-image 适配
23. Provider 错误分类
24. Attempt 重试状态机
25. Deadline 与调用前预算门控
26. Usage 与实际成本汇总
27. 分阶段延迟汇总
28. 统一 fail-closed 脱敏
29. 图谱外 Attempt Log
30. 多模态执行服务编排
31. Semantic Service 执行兼容分组
32. Semantic Service 缓存与调用顺序
33. 既有语义 DTO 结果投影
34. 页面摘要与关系候选临时结果
35. Run、Attempt 与 Payload 受控写回
36. 部分成功与持久化失败语义
37. Facade 产品入口兼容扩展
38. 产品化配置合同
39. Factory 依赖装配
40. 七类 task 离线合同矩阵
41. 安全与静态边界测试
42. 产品化文档同步
43. 专项回归验收

---

## Task 1：执行状态与错误枚举合同

**明确目标：** 定义产品化执行层唯一的 task、运行状态、attempt 状态、provider 错误、usage、cost 和图像角色稳定枚举。

**指定修改文件：**

- 新增：`src/drawing_graph/recognition_models.py`
- 新增：`tests/test_recognition_models.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_models -v
```

**完成标准：**

- 七类 `RecognitionTaskType` 值与 design.md 完全一致。
- 执行、attempt、provider error、usage、cost 和 image role 枚举均使用稳定小写字符串。
- 未知枚举值被拒绝，不依赖供应商中文文案。
- 模块不导入 Neo4j、repository、HTTP/MCP/CLI 或 Qwen adapter。

## Task 2：执行策略与请求 DTO

**明确目标：** 定义可验证的 `RecognitionExecutionPolicy`、`RecognitionExecutionRequest` 和 `ValidatedRecognitionRequest` 输入合同。

**指定修改文件：**

- 修改：`src/drawing_graph/recognition_models.py`
- 修改：`tests/test_recognition_models.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_models -v
```

**完成标准：**

- 请求能表达 run/page/targets、模型、prompt、输入/输出合同、预处理、deadline 和 `write_back`。
- 策略能表达 max attempts、结构修复上限、退避、jitter、deadline 和调用前成本预算。
- 非法 attempts、负数时限/预算、repair 超过总 attempts 被拒绝。
- `write_back` 默认值为 false，DTO 不接受 key、header 或任意 provider body。

## Task 3：Attempt、计量与执行结果 DTO

**明确目标：** 定义不可变的 provider usage、attempt、成本、延迟、验证输出和执行结果 DTO。

**指定修改文件：**

- 修改：`src/drawing_graph/recognition_models.py`
- 修改：`tests/test_recognition_models.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_models -v
```

**完成标准：**

- `RecognitionAttempt` 包含 run/attempt ID、序号、状态、版本、时长、usage、cost 和安全错误摘要。
- `RecognitionExecutionResult` 能表达 validated outputs、candidate evidence、attempts、usage/cost/latency、warnings、payload ref 和 persisted。
- unavailable 与数值 0 可区分；未知实际成本使用 null 而不是 0。
- bytes、prompt、Authorization、绝对路径和 traceback 不属于公开 DTO 字段。

## Task 4：Task Registry 基础机制

**明确目标：** 建立不可变 `RecognitionTaskRegistry` 和 `RecognitionTaskSpec` 注册、查询接口。

**指定修改文件：**

- 新增：`src/drawing_graph/recognition_tasks.py`
- 新增：`tests/test_recognition_tasks.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_tasks -v
```

**完成标准：**

- 提供 `get()`、`list_specs()` 和 `validate_registry()`。
- task spec 固定绑定 target types、prompt、输入/输出合同、crop policy、required outputs 和结构修复许可。
- 重复 task、空版本、空 schema ID 和可变注册表被拒绝。
- registry 不调用 provider、文件系统、数据库或环境变量。

## Task 5：page_summary task spec

**明确目标：** 注册只允许页面目标、使用受控整页缩放且不新增图谱节点的 `page_summary` 合同。

**指定修改文件：**

- 修改：`src/drawing_graph/recognition_tasks.py`
- 修改：`tests/test_recognition_tasks.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_tasks.RecognitionTaskSpecTests.test_page_summary_spec -v
```

**完成标准：**

- target type 仅允许 DrawingPage。
- required outputs 明确为 summary、key_elements、uncertainties。
- crop policy 明确为整页受控缩放。
- 写回声明仅允许 run/payload，不声明 PageInterpretation。

## Task 6：element_text_observation task spec

**明确目标：** 注册用于图内文字观察、强制局部 crop 的 `element_text_observation` 合同。

**指定修改文件：**

- 修改：`src/drawing_graph/recognition_tasks.py`
- 修改：`tests/test_recognition_tasks.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_tasks.RecognitionTaskSpecTests.test_element_text_observation_spec -v
```

**完成标准：**

- 仅允许 BlockCaption、TableCaption、PlainText、Title 和 DrawingAnnotation。
- 必须有 element ID、bbox 和 normalized bbox。
- required output 为 observations，图像策略为局部 crop。
- 允许写回类型仅为 TextObservation。

## Task 7：block_semantic_identification task spec

**明确目标：** 注册 DrawingBlock 语义识别及最小上下文规则。

**指定修改文件：**

- 修改：`src/drawing_graph/recognition_tasks.py`
- 修改：`tests/test_recognition_tasks.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_tasks.RecognitionTaskSpecTests.test_block_semantic_identification_spec -v
```

**完成标准：**

- 主目标仅允许 DrawingBlock。
- 图像策略为局部 crop 加白名单最小 context。
- 输出合同允许 block interpretation 和可选 observation。
- 写回声明不允许修改 `DrawingBlock.block_type`。

## Task 8：basic_info_interpretation task spec

**明确目标：** 注册 DrawingBasicInfo 的文字观察与结构解释合同。

**指定修改文件：**

- 修改：`src/drawing_graph/recognition_tasks.py`
- 修改：`tests/test_recognition_tasks.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_tasks.RecognitionTaskSpecTests.test_basic_info_interpretation_spec -v
```

**完成标准：**

- 主目标仅允许 DrawingBasicInfo，且强制局部 crop。
- 输出合同包含 raw text、summary 和现有结构字段。
- 写回类型限定为 BasicInfoInterpretation 和可选 TextObservation。
- 不引入新的来源事实字段。

## Task 9：table_interpretation task spec

**明确目标：** 注册 Table 解释和受限 caption context 合同。

**指定修改文件：**

- 修改：`src/drawing_graph/recognition_tasks.py`
- 修改：`tests/test_recognition_tasks.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_tasks.RecognitionTaskSpecTests.test_table_interpretation_spec -v
```

**完成标准：**

- 主目标仅允许 Table，context 仅允许同页 TableCaption。
- 输出合同包含 summary、caption_ref 和 uncertainties。
- 图像策略为表格局部 crop 加有限 caption context。
- 写回类型仅为 TableInterpretation。

## Task 10：section_label_observation task spec

**明确目标：** 注册 CrossSection/BlockCaption 断面标签观察合同。

**指定修改文件：**

- 修改：`src/drawing_graph/recognition_tasks.py`
- 修改：`tests/test_recognition_tasks.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_tasks.RecognitionTaskSpecTests.test_section_label_observation_spec -v
```

**完成标准：**

- 主目标仅允许 CrossSection 或 BlockCaption。
- 输出合同区分 raw label 与 normalized label observation。
- 图像策略强制局部 crop。
- 结果只能写 TextObservation，不能直接写匹配关系。

## Task 11：relation_evidence_extraction task spec

**明确目标：** 注册只产生候选证据、不直接写关系的 relation evidence 合同。

**指定修改文件：**

- 修改：`src/drawing_graph/recognition_tasks.py`
- 修改：`tests/test_recognition_tasks.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_tasks.RecognitionTaskSpecTests.test_relation_evidence_extraction_spec -v
```

**完成标准：**

- 合同要求一个主目标和同页白名单 context IDs。
- required output 为 candidate evidence 与 supporting IDs。
- 输出事实等级固定为 candidate_relation。
- 写回声明只允许 run/payload，不允许 candidate/formal 图谱边。

## Task 12：Task Registry 完整性校验

**明确目标：** 用注册表级合同保证七类 task 的版本、schema、prompt 和 crop policy 完整且互不串线。

**指定修改文件：**

- 修改：`src/drawing_graph/recognition_tasks.py`
- 修改：`tests/test_recognition_tasks.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_tasks.RecognitionTaskRegistryIntegrityTests -v
```

**完成标准：**

- registry 恰好包含七类稳定 task。
- 每类 task 均有非空且可版本化的 prompt/input/output/preprocessing/crop 标识。
- 不同 task 不共享错误的 target 白名单或 required outputs。
- registry 多次构造和枚举顺序确定一致。

## Task 13：目标身份与类型输入校验

**明确目标：** 在 provider 调用前验证 page、target、element 与 task 允许类型的一致性。

**指定修改文件：**

- 新增：`src/drawing_graph/recognition_input_validation.py`
- 新增：`tests/test_recognition_input_validation.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_input_validation.RecognitionIdentityValidationTests -v
```

**完成标准：**

- page ID、target ID、element ID 必须能在传入 PageSourceFacts 中相互对应。
- task 不存在、target type 不允许或稳定 ID 串线时抛出 `RecognitionInputError`。
- page_summary 的 page target 例外被显式验证，不放宽其他 task。
- 输入失败不创建 provider attempt。

## Task 14：bbox 与同页 context 输入校验

**明确目标：** 严格验证 bbox、normalized bbox、图片尺寸和 context 的同页白名单约束。

**指定修改文件：**

- 修改：`src/drawing_graph/recognition_input_validation.py`
- 修改：`tests/test_recognition_input_validation.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_input_validation.RecognitionSpatialValidationTests -v
```

**完成标准：**

- 负面积、越界、NaN/Infinity、与 normalized bbox 不一致的坐标被拒绝。
- 非 page task 缺少 bbox 时被拒绝。
- context ID 必须同页并属于 task spec 白名单。
- 校验只读传入 source facts，不访问 Neo4j 或文件系统。

## Task 15：输入安全字段与执行策略校验

**明确目标：** 拒绝输入上下文中的 secret、路径、未知字段和越权执行参数。

**指定修改文件：**

- 修改：`src/drawing_graph/recognition_input_validation.py`
- 修改：`tests/test_recognition_input_validation.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_input_validation.RecognitionSecurityValidationTests -v
```

**完成标准：**

- Authorization、token/key/password/secret、绝对路径和未知 context 字段被拒绝。
- model、prompt、合同和 preprocessing version 必须与 task spec 一致。
- 调用者只能收紧服务端 attempts/deadline/预算，不能放宽。
- `write_back` 必须为显式布尔语义，默认 false。

## Task 16：局部 bbox 内存裁剪

**明确目标：** 使用 Pillow 将已验证元素 bbox 转换为不落盘的 `PreparedRecognitionImage`。

**指定修改文件：**

- 修改：`requirements.txt`
- 新增：`src/drawing_graph/recognition_image_preprocessing.py`
- 新增：`tests/test_recognition_image_preprocessing.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_image_preprocessing.RegionCropTests -v
```

**完成标准：**

- 依赖固定为 `Pillow>=10,<13`，不引入 OpenCV 或 OCR。
- element/block/table/section task 按版本化 padding 裁剪正确像素区域。
- 结果保存在 BytesIO/bytes 生命周期中，不创建 crop 文件。
- prepared image 记录 role、mime、hash、bbox、输入/输出尺寸和 preprocessing version，repr 不泄露 bytes。

## Task 17：图像方向、缩放与资源上限

**明确目标：** 对整页和 context 图像执行固定方向规范化、受控缩放及解码资源保护。

**指定修改文件：**

- 修改：`src/drawing_graph/recognition_image_preprocessing.py`
- 修改：`tests/test_recognition_image_preprocessing.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_image_preprocessing.ImageSafetyTests -v
```

**完成标准：**

- page_summary 使用整页受控缩放，context 使用 task spec 指定低分辨率版本。
- EXIF orientation 处理固定并进入 preprocessing version。
- 文件字节、像素、边长、crop 面积、损坏图片和 decompression bomb 均有 fail-closed 上限。
- source path 不进入 PreparedRecognitionImage、异常或日志字段。

## Task 18：task-specific prompt 渲染

**明确目标：** 按 task spec 渲染供应商无关 prompt，并生成稳定版本与 fingerprint。

**指定修改文件：**

- 新增：`src/drawing_graph/recognition_prompting.py`
- 新增：`tests/test_recognition_prompting.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_prompting -v
```

**完成标准：**

- 七类 task 输出各自 instruction、schema ID/version、prompt version 和 image role 顺序。
- 图中文字被声明为数据而非指令，未知/不确定结果使用约定状态。
- renderer 只插入白名单安全字段，不包含 key、路径、无关页面文本或完整候选集。
- 同一规范化输入产生相同 fingerprint；prompt/version 变化会改变 fingerprint。

## Task 19：JSON 与 task schema 输出校验

**明确目标：** 将 provider payload 严格验证为对应 task 的 `ValidatedRecognitionOutput`。

**指定修改文件：**

- 新增：`src/drawing_graph/recognition_output_validation.py`
- 新增：`tests/test_recognition_output_validation.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_output_validation.OutputSchemaTests -v
```

**完成标准：**

- 顶层必须为 JSON object，未知字段默认拒绝。
- required outputs、字段类型、枚举、置信度和最大返回数量按 task schema 校验。
- malformed JSON 与 schema failure 使用稳定 `RecognitionOutputContractError`。
- 供应商包装差异只经显式 compatibility mapping 处理。

## Task 20：目标归属与事实等级输出校验

**明确目标：** 阻止模型返回请求外目标或把语义/候选结果越权声明为来源、派生或正式事实。

**指定修改文件：**

- 修改：`src/drawing_graph/recognition_output_validation.py`
- 修改：`tests/test_recognition_output_validation.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_output_validation.OutputAuthorityTests -v
```

**完成标准：**

- output target ID/type 必须属于原请求。
- source、derived、formal 声明和直接关系写入指令被拒绝。
- relation evidence 只能投影为 candidate_relation 且 supporting IDs 必须来自允许上下文。
- ambiguous、not_found 和 contract_failed 不产生可写回语义证据。

## Task 21：Provider Port 与序列化 Fake

**明确目标：** 将现有 multimodal client 收窄为 prepared-image provider port，并提供可按调用序列返回结果的离线 Fake。

**指定修改文件：**

- 修改：`src/drawing_graph/semantic_client.py`
- 修改：`tests/test_semantic_client.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_semantic_client -v
```

**完成标准：**

- request 只含 model、rendered prompt、prepared images、output contract、timeout 和 fingerprint。
- result 只含适配后 payload、provider request ID、model/version 和 usage。
- Fake 可确定性模拟成功、429、5xx、超时、非法 JSON 和 schema failure。
- provider port 不接收本地 image path，不负责 crop、retry 或写回。

## Task 22：Qwen prepared-image 适配

**明确目标：** 让 Qwen/DashScope adapter 只传输 prepared images，并返回最小 provider 元数据与 usage。

**指定修改文件：**

- 修改：`src/drawing_graph/qwen_semantic_client.py`
- 修改：`tests/test_qwen_semantic_client.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_qwen_semantic_client -v
```

**完成标准：**

- adapter 使用执行层提供的 prompt 和内存图片，不读取 source facts 或自行裁图。
- 解析 request ID、model/version 和 usage，不向上返回 header、原始 error body 或 key。
- 非测试非 loopback endpoint 强制 HTTPS，拒绝 URL userinfo 和不安全重定向。
- 测试使用 mock transport，不调用 live DashScope。

## Task 23：Provider 错误分类

**明确目标：** 将 HTTP/网络/认证/限流/超时/永久错误映射为稳定 `RecognitionProviderError` 类别。

**指定修改文件：**

- 新增：`src/drawing_graph/recognition_retry.py`
- 新增：`tests/test_recognition_retry.py`
- 修改：`src/drawing_graph/qwen_semantic_client.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_retry.ProviderErrorClassificationTests -v
```

**完成标准：**

- 429、暂时性 5xx、连接重置和 timeout 被正确标记为有条件可重试。
- authentication、permission、永久 4xx 和 invalid response 被标记为终止性错误。
- Retry-After 仅接受可解析、有界值。
- 错误对象只含 category、retryable、有限 retry-after 和 safe message。

## Task 24：Attempt 重试状态机

**明确目标：** 实现每次 provider 调用生成一个 attempt 的有界重试与结构修复状态机。

**指定修改文件：**

- 修改：`src/drawing_graph/recognition_retry.py`
- 修改：`tests/test_recognition_retry.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_retry.RecognitionAttemptExecutorTests -v
```

**完成标准：**

- attempt_number 从 1 单调递增并始终属于同一 run。
- 可重试错误按有界指数退避和 jitter 重试；认证/权限/永久错误不重试。
- 非法 JSON/schema 最多执行一次显式允许的结构修复。
- retry 不改变 task、target、bbox、prompt、合同或 request fingerprint。

## Task 25：Deadline 与调用前预算门控

**明确目标：** 在每次 attempt 前强制检查总 deadline、剩余 attempts 和预计新增成本。

**指定修改文件：**

- 修改：`src/drawing_graph/recognition_retry.py`
- 修改：`tests/test_recognition_retry.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_retry.RecognitionExecutionGateTests -v
```

**完成标准：**

- 剩余 deadline 不足时不发起新调用并返回 deadline_exceeded。
- max attempts 或成本预算耗尽时不发起新调用。
- clock、sleeper 和 jitter source 可注入，离线测试不真实等待。
- gate 不扩大图片、目标或 context 范围。

## Task 26：Usage 与实际成本汇总

**明确目标：** 从 attempts 和版本化 rate card 生成 usage 与实际/估算成本摘要。

**指定修改文件：**

- 新增：`src/drawing_graph/recognition_metrics.py`
- 新增：`tests/test_recognition_metrics.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_metrics.RecognitionUsageCostTests -v
```

**完成标准：**

- 汇总 input/output/image units，所有 retry 和修复 attempt 均计费。
- rate card 含 provider、model、currency 和 version ID。
- usage/rate card 缺失时状态为 unavailable，actual cost 为 null。
- 03 的 `RecognitionEstimate` 保持预计值，不被实际成本覆盖。

## Task 27：分阶段延迟汇总

**明确目标：** 记录并汇总 validation、preprocessing、provider、backoff、output validation 和 total 延迟。

**指定修改文件：**

- 修改：`src/drawing_graph/recognition_metrics.py`
- 修改：`tests/test_recognition_metrics.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_metrics.RecognitionLatencyTests -v
```

**完成标准：**

- 每次 provider attempt 和每段 backoff 可单独追溯。
- total 与分阶段合计关系在固定 clock 下确定。
- cache hit 不产生 provider/backoff 延迟和 attempt。
- 延迟字段不包含 prompt、图片或 provider 原始 payload。

## Task 28：统一 fail-closed 脱敏

**明确目标：** 为异常、payload 和 trace 提供统一、失败即拒绝的脱敏能力。

**指定修改文件：**

- 新增：`src/drawing_graph/recognition_redaction.py`
- 新增：`tests/test_recognition_redaction.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_redaction -v
```

**完成标准：**

- 屏蔽 key/token/password/secret/cookie/Authorization、header、绝对路径、Base64/data URL、bytes、prompt、provider body 和 traceback。
- 嵌套 mapping/sequence 与异常对象均被递归处理。
- 未知不可安全序列化对象被删除或拒绝，不原样输出。
- 输出仅保留稳定 error code/category、safe summary 和非敏感 ID。

## Task 29：图谱外 Attempt Log

**明确目标：** 实现 append-only、图谱外且可按 run 查询的 RecognitionAttemptLog port 与内存实现。

**指定修改文件：**

- 新增：`src/drawing_graph/recognition_attempt_log.py`
- 新增：`tests/test_recognition_attempt_log.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_attempt_log -v
```

**完成标准：**

- 提供 `append_attempt()` 和 `list_attempts(recognition_run_id)`。
- attempt ID 幂等、编号稳定、既有记录不可覆盖。
- 日志拒绝图片、prompt、header、secret、路径和原始 provider error。
- 实现不依赖 Neo4j；dry-run 约束由上层保证且有测试桩可断言零调用。

## Task 30：多模态执行服务编排

**明确目标：** 实现 04 唯一执行入口，按固定顺序串联 task、输入、图像、prompt、attempt、输出、计量与脱敏。

**指定修改文件：**

- 新增：`src/drawing_graph/recognition_execution.py`
- 新增：`tests/test_recognition_execution.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_execution -v
```

**完成标准：**

- 提供 `MultimodalRecognitionExecutionService.execute(request, page_facts, execution_policy=None)`。
- 编排顺序与 design.md 一致，输入失败时 provider 零调用。
- 返回 validated outputs、attempts、usage/cost/latency、warnings 和安全错误。
- 执行服务不写 cache、run log、attempt log、payload store 或 Neo4j。

## Task 31：Semantic Service 执行兼容分组

**明确目标：** 将 cache miss targets 按 page/task/model/prompt/合同/preprocessing/crop policy 稳定分组。

**指定修改文件：**

- 修改：`src/drawing_graph/semantic_service.py`
- 修改：`tests/test_semantic_service.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_semantic_service.SemanticExecutionGroupingTests -v
```

**完成标准：**

- 同 task 且兼容版本的 targets 可同组，不同 task/版本不得合并。
- 分组键与组内 target 顺序稳定。
- 一次 Facade 调用仍对应一个逻辑 run。
- Service 不生成 task prompt 或自行裁图。

## Task 32：Semantic Service 缓存与调用顺序

**明确目标：** 保证统一 cache key 的二次命中发生在 run、attempt 和 provider 调用之前。

**指定修改文件：**

- 修改：`src/drawing_graph/semantic_service.py`
- 修改：`tests/test_semantic_service.py`
- 修改：`tests/test_semantic_cache.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_semantic_service.SemanticExecutionCacheOrderTests tests.test_semantic_cache -v
```

**完成标准：**

- 继续复用 `SemanticCacheKeyInput` 和 `build_semantic_cache_key()`，不复制算法。
- cache hit 不调用 execution service/provider，不创建 attempt 或持久化 run，不产生费用。
- 只有 cache miss 才构造执行请求。
- 失败和未经合同验证的 provider payload 不进入成功缓存。

## Task 33：既有语义 DTO 结果投影

**明确目标：** 将合同有效的 element/block/basic-info/table/section 输出投影为现有语义 DTO。

**指定修改文件：**

- 修改：`src/drawing_graph/semantic_service.py`
- 修改：`src/drawing_graph/semantic_models.py`
- 修改：`tests/test_semantic_service.py`
- 修改：`tests/test_semantic_models.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_semantic_service.SemanticOutputProjectionTests tests.test_semantic_models -v
```

**完成标准：**

- 输出仅映射为现有 TextObservation、BlockInterpretation、BasicInfoInterpretation、TableInterpretation。
- provenance 保留 run ID、image/bbox hash、model、prompt、合同和 preprocessing 版本。
- ambiguous、not_found、contract_failed 不投影语义证据。
- 不修改 DrawingBlock 来源字段或写正式关系。

## Task 34：页面摘要与关系候选临时结果

**明确目标：** 在 `SemanticRecognitionResult` 中承载 page summary 和 relation candidate evidence，而不新建图谱对象。

**指定修改文件：**

- 修改：`src/drawing_graph/semantic_service.py`
- 修改：`src/drawing_graph/semantic_models.py`
- 修改：`tests/test_semantic_service.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_semantic_service.SemanticTransientOutputTests -v
```

**完成标准：**

- result 增加有默认值的 summary、candidate_evidence、attempts、metrics、payload_ref 和 warnings。
- page summary 不产生 PageInterpretation 节点。
- relation evidence 明确标记 candidate_relation，不调用 relation repository。
- 现有结果构造和序列化保持兼容。

## Task 35：Run、Attempt 与 Payload 受控写回

**明确目标：** 在 `write_back=true` 时保存脱敏 run/attempt/payload 和允许的语义证据。

**指定修改文件：**

- 修改：`src/drawing_graph/semantic_service.py`
- 修改：`src/drawing_graph/recognition_run_log.py`
- 修改：`src/drawing_graph/semantic_payload_store.py`
- 修改：`tests/test_recognition_run_log.py`
- 修改：`tests/test_semantic_payload_store.py`
- 修改：`tests/test_semantic_service_write_back.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_run_log tests.test_semantic_payload_store tests.test_semantic_service_write_back -v
```

**完成标准：**

- run summary 增加带默认值的 attempt IDs、usage/latency 和合同/preprocessing 版本。
- payload 写入前强制 redactor，禁止 bytes、Base64、路径、prompt、header 和原始错误。
- dry-run 对 run/attempt/payload/repository 全部零写入。
- page summary/relation evidence 仅保存图谱外 run/attempt/payload，不写节点或关系。

## Task 36：部分成功与持久化失败语义

**明确目标：** 明确定义多分组 partial、成功结果保留和 `persisted=false` 行为。

**指定修改文件：**

- 修改：`src/drawing_graph/semantic_service.py`
- 修改：`tests/test_semantic_service.py`
- 修改：`tests/test_semantic_service_write_back.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_semantic_service.SemanticPartialResultTests tests.test_semantic_service_write_back -v
```

**完成标准：**

- 至少一组成功且一组失败时状态为 partial，成功证据保留。
- 失败组只有安全 warning/error，不产生语义证据或成功缓存。
- 业务输出成功但持久化失败时返回 `persisted=false`，不伪报写回成功。
- 已保存 payload 而语义写回失败时保留审计引用，不自动删除或伪造回滚。

## Task 37：Facade 产品入口兼容扩展

**明确目标：** 在现有精确目标入口增加可选执行策略，同时保持受控路径和默认 dry-run。

**指定修改文件：**

- 修改：`src/drawing_graph/tool_facade.py`
- 修改：`src/drawing_graph/tool_models.py`
- 修改：`tests/test_tool_facade.py`
- 修改：`tests/test_tool_models.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_tool_facade tests.test_tool_models -v
```

**完成标准：**

- `recognize_semantic_targets(..., write_back=False, execution_policy=None)` 保持现有调用兼容。
- `SemanticTargetInput` 仅增加有默认值的 input contract 与 preprocessing version。
- Facade 拒绝跨页目标，不接受 image path、key、provider header 或任意 prompt。
- Facade 不创建 driver、不写 Cypher、不直接调用 repository。

## Task 38：产品化配置合同

**明确目标：** 增加非 secret 的 retry、deadline、图像、预处理和 rate-card 配置及校验。

**指定修改文件：**

- 修改：`src/drawing_graph/config.py`
- 修改：`tests/test_config.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_config -v
```

**完成标准：**

- 配置字段与 design.md 3.10 的名称和默认值一致。
- 负数、非法 attempts、repair 超限、非法 jitter 和图像上限被拒绝。
- 配置 DTO 不包含 DASHSCOPE_API_KEY 或其他 secret。
- API key 仍只由 `QwenRecognitionConfig.from_env()` 读取。

## Task 39：Factory 依赖装配

**明确目标：** 在 factory 中装配 registry、validator、preprocessor、renderer、validator、retry、meter、redactor、attempt log 和 execution service。

**指定修改文件：**

- 修改：`src/drawing_graph/tool_factory.py`
- 修改：`tests/test_tool_factory.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_tool_factory -v
```

**完成标准：**

- 默认 provider 仍为 Fake，仅显式 qwen 配置才创建 Qwen adapter。
- factory 将同一 execution service 注入 SemanticRecognitionService，不复制实例职责。
- Fake 装配不读 API key、不联网、不连接 Neo4j。
- 非法配置在创建 provider 调用前失败。

## Task 40：七类 task 离线合同矩阵

**明确目标：** 建立完全离线的七类 task 输入、输出、错误与执行合同矩阵。

**指定修改文件：**

- 新增：`tests/test_multimodal_recognition_contracts.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_multimodal_recognition_contracts -v
```

**完成标准：**

- 每类 task 覆盖合法最小输入/输出、非法 target/bbox/context、未知字段和错误事实等级。
- 覆盖 429、5xx、timeout、认证、非法 JSON、schema failure、deadline、成本、attempt 和 cache hit。
- 全部使用 Fake、固定 clock/sleeper/jitter 和内存 ports，不需要网络、Neo4j 或 DashScope key。
- dry-run 零持久化、write-back 矩阵和 partial 结果均有跨模块离线断言。

## Task 41：安全与静态边界测试

**明确目标：** 用静态测试防止执行层越权依赖、敏感数据字段和绕过 Facade/Service 的调用路径。

**指定修改文件：**

- 新增：`tests/test_multimodal_recognition_boundaries.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_multimodal_recognition_boundaries -v
```

**完成标准：**

- 执行层禁止导入 Neo4j driver、repository、Cypher、HTTP/MCP/CLI adapter。
- Qwen adapter 不包含 task registry、crop、retry loop、cost、redaction 或 write-back 逻辑。
- DTO、run、attempt、payload 与异常字段不允许 key、Authorization、绝对路径、Base64、完整 prompt 或 traceback。
- 测试确认 `write_back=false` 默认值和 candidate/formal 边界仍存在。

## Task 42：产品化文档同步

**明确目标：** 实施完成后同步直接相关架构、模块、配置和产品阶段文档。

**指定修改文件：**

- 修改：`architecture.md`
- 修改：`Module.md`
- 修改：`README.md`
- 修改：`.env.example`
- 修改：`changes/产品实现层/04-multimodal-recognition.md`
- 修改：`changes/产品实现层/多模态识别产品化/design.md`
- 修改：`changes/产品实现层/多模态识别产品化/Feature_Analysis_Report.md`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_docs tests.test_semantic_docs tests.test_readme tests.test_module_docs -v
```

**完成标准：**

- 文档准确说明新执行层、七类 task、局部 bbox、retry/attempt、cost/latency、脱敏和离线合同。
- 文档继续声明默认 `write_back=false`、run/attempt 图谱外、candidate 不等于 formal、无 OCR 和无 Neo4j schema 变化。
- `.env.example` 只列变量名和安全占位说明，不包含真实 key。
- 离线、live DashScope、黄金集、live Neo4j、Codex/MCP 的状态分开陈述，skipped 不算通过。

## Task 43：专项回归验收

**明确目标：** 用一个产品化专项验收入口证明文档合同、兼容入口和关键离线回归共同成立。

**指定修改文件：**

- 新增：`tests/test_multimodal_recognition_docs.py`
- 新增：`tests/test_multimodal_recognition_acceptance.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_multimodal_recognition_docs tests.test_multimodal_recognition_acceptance tests.test_multimodal_recognition_contracts tests.test_multimodal_recognition_boundaries tests.test_tool_facade tests.test_semantic_service tests.test_qwen_semantic_client -v
```

**完成标准：**

- 文档测试确认 proposal、design、analysis、tasks 四份文件存在且边界一致。
- acceptance 测试覆盖 cache hit、局部 bbox、一次 retry、attempt/usage/cost/latency、脱敏和 dry-run 零持久化最小闭环。
- Facade、Semantic Service 和 Qwen adapter 现有兼容测试全部通过。
- 失败时只修复本需求直接相关文件，不进行无关重构。
- 测试输出明确属于 offline/fake 验证，不声明 live DashScope、live Neo4j 或 Codex/MCP 已通过。

---

## 实施顺序与评审门

- Tasks 1-4 建立公共合同；Tasks 5-12 逐个锁定七类 task。
- Tasks 13-20 建立调用前后严格合同；未通过这些任务不得接入真实 provider。
- Tasks 21-30 建立 provider、重试、计量、脱敏、attempt 和执行编排。
- Tasks 31-39 接入现有 Service、持久化、Facade 和 factory。
- Tasks 40-43 分别完成离线合同、安全边界、文档同步和专项回归。
- 每个 Task 必须独立评审、独立测试后才进入下一项；不得以最终大回归替代该 Task 的专项测试。
- live DashScope 与 live Neo4j 需要单独环境授权和验证计划，不属于离线实施任务的完成前提，也不得被离线结果冒充。
