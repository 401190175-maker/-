# 产品公共合同与通用检索闭环需求分析报告

**文档状态：** 新需求分析  
**日期：** 2026-08-11  
**分析范围：** 产品公共合同与通用检索闭环  
**输入文档：**

- `architecture.md`
- `Module.md`（用户请求中写作 `modules.md`；当前工作区实际文件名为 `Module.md`）
- `changes/产品实现层/00-product-closure-blueprint.md`
- `changes/产品实现层/01-question-understanding.md`
- `changes/产品实现层/02-graph-retrieval.md`
- `changes/产品实现层/03-semantic-gap-decision.md`
- `changes/产品实现层/04-multimodal-recognition.md`
- `changes/产品实现层/05-evidence-fusion-and-cache.md`
- `changes/产品实现层/06-answer-generation.md`
- `changes/产品实现层/07-traceability-and-feedback.md`

> 注：用户请求中的 `图块图谱构造/` 在当前工作区未发现同名子目录；本报告基于当前项目根目录 `C:\Users\40119\Desktop\图块图谱构建` 下已验证存在的文档。

## 1. 需求理解

“增加产品公共合同与通用检索闭环”不是单一业务能力，而是对现有产品实现层 00-07 文档的横向补强：

1. **产品公共合同**：把 `AssistantRequest`、`QuestionUnderstandingResult`、`EvidenceRequirement`、`RetrievalBundle`、`SemanticGapDecision`、`RecognitionRequest`、`RecognitionResult`、`EvidenceBundle`、`AnswerPackage`、`TraceRecord`、`FeedbackEvent` 等跨模块 DTO、枚举、状态码、错误码、证据引用和序列化规则统一沉淀为公共契约，避免每个模块重复定义或语义漂移。
2. **通用检索闭环**：把“问题理解产生证据需求 -> 查询计划 -> facade 只读检索 -> 缺口标记 -> 证据分层输出 -> 供缺口判断/融合/回答复用”做成稳定闭环，而不是继续依赖现有 `DrawingGraphQAService` 的六类固定问答路由。

这项需求的目标应是产品层可组合、可测试、可扩展，而不是替代当前 `DrawingGraphToolFacade`、`DrawingGraphQAService`、HTTP API 或 MCP adapter。

## 2. 当前架构是否支持？

### 2.1 支持的部分

当前架构已经具备较好的底座：

- `DrawingGraphToolFacade` 已经统一封装图纸册、页面、页面来源事实、图块追溯、图块关系、候选关系、语义 observation、interpretation、payload、断面匹配等能力。
- `QAAnswer`、`AnswerFact`、`EvidenceRef` 已经建立了事实分层意识，能区分 `source_fact`、`derived_relation`、`semantic_observation`、`semantic_interpretation`、`candidate_relation`、`formal_relation`、`diagnostic`、`unsupported`。
- `DrawingGraphQAService`、CLI、HTTP、MCP adapter 已形成只读 QA 编排入口，并保持 `QA adapter -> DrawingGraphQAService -> DrawingGraphToolFacade -> ports/services -> repository/Neo4j` 的依赖方向。
- 语义证据层已经具备 `RecognitionRun` 图谱外日志、图谱内 `TextObservation`/`Interpretation`、缓存键、payload、断面匹配和默认 `write_back=false` 边界。
- 产品实现层 00-07 已经明确提出七模块闭环，并在 02 中提出 `RetrievalBundle`，在 05 中提出 `EvidenceItem`，在 06 中提出 `Claim`，在 07 中提出 `TraceRecord`/`FeedbackEvent`。

结论：**当前架构支持新增产品公共合同与通用检索闭环，但需要新增产品层模块与公共契约层。**

### 2.2 不足的部分

当前架构尚不足以直接完成该需求：

- 公共合同分散在 00-07 文档中，尚未成为一个可被所有模块复用的权威契约。
- `QARequest`/`QAAnswer` 面向现有固定问答，不足以覆盖产品闭环中的多意图、证据需求、识别策略、融合、claim、追溯和反馈。
- `DrawingGraphQAService` 目前按固定问题类型手写调用组合，不是按照 `EvidenceRequirement` 动态生成最小查询计划。
- 当前没有统一的 `RetrievalPlanner`、`RetrievalExecutor`、`RetrievalBundleBuilder` 或检索结果归一化规则。
- 缺少跨模块统一错误码、状态码、原因码、版本号、合同版本、数据最小化和敏感信息脱敏规则。
- 缺少“一次产品请求”的闭环上下文：`request_id`、`subrequest_id`、模块事件、source calls、warnings、missing evidence、trace record 尚未串成统一运行轨迹。

结论：**现有底座够强，但产品公共合同和通用检索闭环本身尚未落地。**

## 3. 需要新增哪些模块？

建议新增以下模块，先作为产品实现层设计对象，后续再进入实施计划。

### 3.1 产品公共合同模块

目标：统一跨模块 DTO、枚举、错误码、状态码、证据引用和序列化边界。

建议职责：

- 定义产品层请求与响应：`AssistantRequest`、`AssistantResponse` 或 `AnswerPackage`。
- 定义问题理解结果：`QuestionUnderstandingResult`、`AssistantSubrequest`、`QAScope` 扩展或产品层 `AssistantScope`。
- 定义证据需求：`EvidenceRequirement`、`EvidenceType`、`MinimumEvidenceStatus`、`FreshnessPolicy`。
- 定义统一证据：`EvidenceItem`、`EvidenceRef`、`EvidenceBundle`、`Claim`、`Citation`。
- 定义状态与原因码：answer status、retrieval status、gap decision、recognition status、cache status、feedback status、reason code。
- 定义合同版本：`contract_version`、`output_contract_version`、`prompt_version` 的传递规则。
- 定义错误 envelope 与脱敏规则，避免 HTTP/MCP/CLI 各自重复。

实施命名已冻结：

- `assistant_models.py`
- `assistant_retrieval_planner.py`
- `assistant_retrieval_executor.py`
- `assistant_retrieval_projection.py`
- `assistant_retrieval_service.py`
- `assistant_qa_mapping.py`

具体源码命名以实施计划冻结结果为准，本报告不写代码。

### 3.2 通用检索规划模块

目标：把 `EvidenceRequirement` 转为可执行、最小、只读、可去重的 facade 查询计划。

建议职责：

- 校验 scope 是否足够。
- 根据证据需求选择 facade 能力。
- 生成 `RetrievalPlan` 和 `RetrievalStep`。
- 合并重复需求。
- 标记必须查询、可选查询和按需 payload 展开。
- 设置分页、limit、截断策略和 source call 记录。

### 3.3 通用检索执行模块

目标：执行检索计划，只通过 `DrawingGraphToolFacade` 或新增受控只读 port 获取数据。

建议职责：

- 调用 facade 的只读能力。
- 区分 not found、empty、partial、degraded、error。
- 将每次调用记录为 `source_calls`。
- 支持同请求内去重和可选并发。
- 不调用 Qwen、不创建 run log、不写 Neo4j。

### 3.4 检索结果归一化模块

目标：将 facade DTO、现有 `QAAnswer` 事实、语义投影和候选关系统一映射为 `RetrievalBundle`。

建议职责：

- 保留 `fact_kind`，不得把 candidate、interpretation、formal 混淆。
- 给每条证据生成稳定 `evidence_id`。
- 统一 `ids`、`scope`、`value`、`status`、`evidence_refs`、`created_at_or_version`。
- 记录 `missing_evidence`、`warnings`、`diagnostics`。

### 3.5 产品编排服务模块

目标：在 00 蓝图中的 `DrawingAssistantService` 内串起公共合同和通用检索闭环。

建议职责：

- 接收 `AssistantRequest`。
- 调用问题理解模块产生 `EvidenceRequirement`。
- 调用通用检索闭环获取 `RetrievalBundle`。
- 调用语义缺口判断模块。
- 必要时触发多模态识别。
- 调用证据融合、答案生成、追溯反馈模块。

注意：该模块不应绕过 facade，也不应替代 `DrawingGraphQAService` 的兼容职责。

### 3.6 产品合同测试与架构边界测试

目标：保护合同不漂移、事实分层不混淆、adapter 不绕过服务边界。

建议覆盖：

- DTO 序列化/反序列化合同测试。
- `fact_kind` 不变性测试。
- `EvidenceRequirement -> RetrievalPlan -> facade call` 映射测试。
- candidate 不可满足 formal requirement 的安全测试。
- `write_back=false` 无副作用测试。
- 架构静态测试：产品检索模块不得导入 Neo4j driver、repository、Cypher、CLI 脚本。

## 4. 影响哪些已有模块？

### 4.1 `DrawingGraphToolFacade`

影响：中等。

它仍是核心受控入口，不应被替代。通用检索闭环会大量消费 facade 已有只读接口，可能暴露少量能力缺口。

可能需要后续扩展：

- 更统一的页面/元素查找接口。
- 更细粒度的 observation/interpretation 查询过滤。
- payload 按需读取的权限和大小控制。
- 批量只读接口，降低页面级检索的调用次数。

### 4.2 `tool_models.py`

影响：中等。

现有 Tool DTO 可作为产品公共合同的证据来源，但不建议直接把 Tool DTO 当作产品公共合同。Tool DTO 更贴近 facade，产品合同应更贴近端到端问答。

建议：产品合同引用或投影 Tool DTO，而不是反向污染 facade DTO。

### 4.3 `qa_models.py` / `qa_service.py`

影响：高。

现有 QA 层是固定六类问答兼容层。新增产品公共合同后，需要明确两者关系：

- `DrawingGraphQAService` 保留为稳定只读 QA 兼容层。
- 新增 `DrawingAssistantService` 负责自然语言产品闭环。
- 旧 QA 模型可被适配为产品合同的一种输入/输出子集，但不应强行扩展到承载全部产品闭环。

### 4.4 `qa_serialization.py`

影响：中等。

现有序列化和错误脱敏能力可复用。后续可能需要抽出更通用的产品层 serialization/envelope，避免 CLI、HTTP、MCP、产品服务各自维护 JSON 规则。

### 4.5 `semantic_models.py` / `semantic_service.py` / `semantic_query_projection.py`

影响：中等。

公共合同需要引用语义证据状态、模型 profile、prompt version、payload ref、cache key、recognition run id。通用检索闭环需要读取语义投影但不应触发识别。

### 4.6 `semantic_cache.py` / `semantic_payload_store.py`

影响：低到中。

主要由语义缺口判断和融合模块读取其状态语义。公共合同需要统一 `cache_status`、`payload_ref`、`contract_version` 表达。

### 4.7 `candidate_review.py` / `relation_repository.py`

影响：低到中。

通用检索闭环只读候选关系，不负责审核和提升。反馈闭环可能发起审核，但仍必须通过 `CandidateReviewService` 与硬规则。

### 4.8 CLI / HTTP / MCP adapter

影响：中到高。

短期：保持现有 QA adapter 不变。  
中期：新增产品级 adapter 路由，例如 `assistant ask`、`POST /api/v1/drawing-assistant/ask`、MCP 产品级工具。  
长期：旧六类 QA 路由可作为兼容能力保留，产品级路由成为自然语言入口。

### 4.9 测试模块

影响：高。

新增公共合同与通用检索后，测试要从模块单测扩展到合同测试、边界测试、端到端 dry-run 测试和 adapter 兼容测试。

## 5. 技术方案有哪些？

### 方案 A：最小增量方案

只新增产品公共合同文档和少量模型定义，通用检索继续复用/扩展 `DrawingGraphQAService` 的固定路由。

优点：

- 改动小。
- 对现有 CLI/HTTP/MCP 影响最少。
- 可以快速沉淀 `AssistantRequest`、`AnswerPackage` 等 DTO。

缺点：

- `DrawingGraphQAService` 会继续膨胀。
- 通用检索仍会被固定问题类型限制。
- 难以支持多意图、任意证据需求、按需 payload、缺口诊断和产品级 trace。
- 后续 03-07 模块容易继续重复定义合同。

适用场景：只想快速统一术语，不急于实现完整产品闭环。

### 方案 B：公共合同 + 独立通用检索服务

新增产品公共合同模块，并新增独立 `GraphRetrievalService`，由它消费 `QuestionUnderstandingResult` 和 `EvidenceRequirement`，生成并执行 `RetrievalPlan`，输出标准 `RetrievalBundle`。`DrawingGraphQAService` 保留为兼容层，不承载完整产品闭环。

优点：

- 边界清晰，符合 00-07 的产品闭环设计。
- 通用检索真正围绕证据需求工作，而不是围绕固定 QA 问题工作。
- 便于后续接入语义缺口判断、证据融合、答案生成和追溯。
- 能最大限度复用 facade，同时不破坏现有 QA adapter。
- 测试粒度清楚：合同、规划、执行、归一化可分别验证。

缺点：

- 新增模块较多，需要先稳定合同。
- 需要处理公共合同与既有 `qa_models.py`、`tool_models.py` 的边界，避免重复。
- 首次实施需要更多测试。

适用场景：希望按产品闭环长期演进，同时保持现有功能兼容。

### 方案 C：一次性建立完整 DrawingAssistantService

一次性实现公共合同、问题理解、通用检索、缺口判断、识别触发、融合、答案生成、追溯反馈和 adapter。

优点：

- 最快形成完整产品形态。
- 可以端到端验证自然语言问答体验。
- 架构目标一次到位。

缺点：

- 风险大，容易跨越过多边界。
- 需求、合同、模块职责可能在实现中频繁变化。
- Qwen live、Neo4j live、写回、反馈权限、trace 存储等验证复杂度叠加。
- 一旦出错，很难定位是合同、检索、识别、融合还是生成的问题。

适用场景：原型演示优先、允许较大返工时可以考虑；不适合作为当前项目的稳健实施路线。

### 方案 D：以 adapter 为中心扩展 HTTP/MCP

直接在 HTTP 或 MCP 层增加自然语言入口，由 adapter 自行完成问题理解、检索、识别和回答。

优点：

- 表面上用户入口最快。
- 不需要先抽象完整产品服务。

缺点：

- 违反现有依赖方向，adapter 会变厚。
- HTTP/MCP/CLI 容易各自实现一套逻辑，合同漂移。
- 难以复用测试和追溯。
- 增加绕过 facade 或混淆 write_back 边界的风险。

适用场景：不推荐。只适合临时实验，不应进入正式架构。

## 6. 优缺点比较

| 方案 | 架构一致性 | 改动规模 | 可测试性 | 闭环能力 | 兼容风险 | 推荐度 |
|---|---:|---:|---:|---:|---:|---:|
| A 最小增量 | 中 | 低 | 中 | 低 | 低 | 中 |
| B 公共合同 + 独立通用检索 | 高 | 中 | 高 | 高 | 中低 | 高 |
| C 一次性完整助手 | 中 | 高 | 中低 | 最高 | 高 | 低 |
| D adapter 中心扩展 | 低 | 中 | 低 | 中 | 高 | 不推荐 |

## 7. 推荐方案

推荐采用 **方案 B：公共合同 + 独立通用检索服务**。

推荐理由：

1. 它最符合当前架构依赖方向：产品层服务在 facade 外侧，所有图谱能力仍通过 `DrawingGraphToolFacade` 或新增受控只读 port 获取。
2. 它尊重现有 `DrawingGraphQAService` 的价值：保留固定六类 QA 和 CLI/HTTP/MCP 兼容入口，不把它改造成过大的产品编排器。
3. 它能把 00-07 文档中分散的公共 DTO 和状态统一起来，为后续语义缺口、识别、融合、答案、追溯模块提供稳定输入输出。
4. 它便于分阶段验收：先验合同，再验查询计划，再验只读执行，再验缺口判断接入，最后再接自然语言助手。
5. 它能继续维持默认 `write_back=false`、候选不等于正式事实、模型输出不覆盖来源事实等核心安全边界。

建议实施拆分：

1. **公共合同冻结阶段**：统一 `AssistantRequest`、`Scope`、`EvidenceRequirement`、`EvidenceItem`、`RetrievalBundle`、`AnswerPackage`、`TraceRecord` 的字段、枚举和版本。
2. **通用检索闭环阶段**：实现 `EvidenceRequirement -> RetrievalPlan -> facade read calls -> RetrievalBundle`。
3. **兼容接入阶段**：让现有六类 QA 能映射到新公共合同或由新检索服务复用，但不删除旧 QAService。
4. **产品编排阶段**：将问题理解、检索、缺口判断、识别、融合、回答、追溯串入 `DrawingAssistantService`。
5. **adapter 扩展阶段**：再新增产品级 CLI/HTTP/MCP 入口。

## 8. 风险

### 8.1 合同过早膨胀

风险：公共合同想一次覆盖所有未来能力，导致 DTO 复杂、字段大量可空、测试难写。

控制：

- 首版只覆盖 00-07 已明确需要的字段。
- 使用 `contract_version` 管理演进。
- 对暂不实现字段写入“不在首版实现”，不放模糊占位。

### 8.2 与现有 `qa_models.py` 重复或冲突

风险：产品合同和 QA 合同同时存在，字段语义不一致。

控制：

- 明确 `qa_models.py` 是固定 QA 兼容层合同。
- 产品公共合同是端到端助手合同。
- 建立 adapter/mapper，而不是让两个模型互相混入。

### 8.3 通用检索绕过 facade

风险：为了补齐检索能力，直接导入 repository、Neo4j driver 或拼写 Cypher。

控制：

- 架构测试禁止产品检索模块导入 driver、repository、Cypher、CLI 脚本。
- facade 缺能力时先在 `missing_evidence` 中报告，再作为独立任务扩展受控 port。

### 8.4 candidate 与 formal 混淆

风险：检索或融合为了回答更“肯定”，把候选关系、`matched_candidate` 或模型解释当成正式关系。

控制：

- `fact_kind` 在公共合同中设为强约束。
- 检索、融合、答案生成分别测试 candidate 不可满足 formal requirement。
- 中文回答中候选关系必须带“候选、可能、待确认”等限定语。

### 8.5 `write_back` 权限被跨模块误传

风险：自然语言问题或反馈暗示写回，导致识别结果或反馈结果被持久化。

控制：

- `AssistantRequest.allow_write_back` 默认 `false`。
- 问题理解不得从用户语气推断 `allow_write_back=true`。
- 识别、融合、反馈写回必须分别检查请求授权、模块策略、环境权限和 repository 可用性。

### 8.6 检索闭环性能风险

风险：通用检索为了“完整”读取页面全部元素、payload 和历史语义证据，导致响应慢、输出大、成本高。

控制：

- 查询规划先轻量摘要，payload 仅按需读取。
- 同请求内 facade call 去重。
- 页面级集合必须有 limit 和截断 warning。
- 后续需要时再设计批量 facade 只读接口。

### 8.7 多意图与 trace 复杂度

风险：一个自然语言问题拆成多个子请求后，证据、识别运行、claim 和反馈难以追溯。

控制：

- 公共合同强制 `request_id`，多意图强制 `subrequest_id`。
- `TraceRecord` 记录 module events、retrieval calls、decision、recognition run ids、evidence ids、claim ids。
- 不通过进程全局变量或隐式上下文传递请求状态。

### 8.8 live 验证边界被误报

风险：单元测试通过后误称 live Neo4j、live DashScope 或写回闭环已验证。

控制：

- 验证报告分开写：单元测试、离线 fake/model 合同测试、live DashScope、live Neo4j、写回测试。
- skipped 集成测试不得报告为通过。
- `write_back=false` dry-run 通过不等于持久化写回通过。

## 9. 建议完成标准

该需求完成时，至少应满足：

- 有一个权威产品公共合同模块或文档，00-07 不再各自定义冲突字段。
- `EvidenceRequirement` 能稳定转为只读 `RetrievalPlan`。
- 通用检索只通过 facade 或受控只读 port 执行。
- `RetrievalBundle` 中所有证据都有 `fact_kind`、稳定 ID、scope、status 和 evidence refs。
- 空结果、缺失证据、基础设施失败、unsupported 能被区分。
- 候选关系、语义解释、正式关系不会互相冒充。
- `write_back=false` 下检索闭环无持久化副作用。
- 现有 `DrawingGraphQAService`、CLI、HTTP、MCP 兼容行为不被破坏。

## 10. 结论

当前架构已经为“产品公共合同与通用检索闭环”提供了较完整的底座，但该需求本身仍是缺失的产品层基础设施。最稳妥的路线不是把现有 QAService 继续做厚，也不是直接在 HTTP/MCP adapter 中堆自然语言能力，而是先建立公共合同，再建立独立通用检索闭环，最后由 `DrawingAssistantService` 串起 00-07 的完整产品闭环。

推荐下一步进入实施计划前，先把“公共合同字段清单”和“EvidenceRequirement 到 facade 能力映射表”冻结为第一阶段设计基线。

## 11. 技术方案补充

本节根据 `proposal.md` 和 `design.md` 补充可落地技术方案。该方案坚持两个边界：**禁止无意义重构**、**优先复用已有架构**。

### 11.1 系统架构变化

当前 QA、HTTP、MCP 的稳定链路保持不变：

```text
QA adapter
  -> DrawingGraphQAService
  -> DrawingGraphToolFacade
  -> ports / services
  -> controlled repository / Neo4j
```

新增产品公共合同与通用检索闭环后，在产品实现层新增一条并列链路：

```text
Product adapter（后续 CLI / HTTP / MCP / Web UI）
  -> DrawingAssistantService（后续完整产品编排）
       -> GraphRetrievalService
            -> RetrievalPlanner
            -> RetrievalExecutor
            -> RetrievalBundleBuilder
  -> DrawingGraphToolFacade
  -> ports / services
  -> controlled repository / Neo4j
```

首阶段只落地公共合同与 `GraphRetrievalService`，不要求一次性实现完整 `DrawingAssistantService`。现有 `DrawingGraphQAService` 继续作为六类固定只读问答的兼容层，不被改造成产品总编排器。

### 11.2 新增模块

建议新增以下产品层模块：

1. **产品公共合同模块**：定义 `AssistantRequest`、`AssistantScope`、`QuestionUnderstandingResult`、`EvidenceRequirement`、`RetrievalPlan`、`RetrievalStep`、`EvidenceItem`、`RetrievalBundle`、`AnswerPackage`、`Claim`、`TraceRecord`、`FeedbackEvent` 等 DTO 和枚举。
2. **通用检索规划模块**：把 `EvidenceRequirement` 转成只读 `RetrievalPlan`，只做规划，不访问 facade。
3. **通用检索执行模块**：按计划调用 `DrawingGraphToolFacade` 白名单方法，记录 `SourceCallRecord`，不写回。
4. **检索结果归一化模块**：把 facade DTO、语义投影、候选关系和诊断信息映射成统一 `EvidenceItem` 与 `RetrievalBundle`。
5. **通用检索服务模块**：编排 planner、executor、bundle builder，对外提供 `retrieve()`。
6. **合同与边界测试模块**：保护 DTO 版本、事实分层、只读边界和 facade 依赖方向。

这些模块位于产品实现层和 facade 外侧，不应导入 Neo4j driver、repository、Cypher、HTTP 框架、MCP SDK、Qwen 客户端或 CLI 脚本。

实施命名已冻结：产品公共合同模块为 `assistant_models.py`，规划/执行/归一化/服务模块分别为 `assistant_retrieval_planner.py`、`assistant_retrieval_executor.py`、`assistant_retrieval_projection.py`、`assistant_retrieval_service.py`，六类 QA 兼容映射为 `assistant_qa_mapping.py`。首阶段实施已落地公共合同与通用检索闭环，并通过合同、规划、执行、归一化、服务编排、QA 映射与静态边界测试；完整 `DrawingAssistantService`、外部产品级 CLI/HTTP/MCP 入口与产品级写回不在首阶段范围。

### 11.3 修改模块

修改策略是“复用为主，必要补口”：

- `DrawingGraphToolFacade`：首版优先使用已有只读接口；只有必要检索能力缺失时，才新增受控只读 facade/port 方法。
- `tool_models.py`：保持 facade DTO 语义稳定，产品合同通过 projection 引用或转换，不反向污染 Tool DTO。
- `qa_models.py` / `qa_service.py`：兼容保留，不删除六类固定 QA 路由；后续可增加 QA 到产品合同的 mapper。
- `qa_serialization.py`：可复用 JSON 转换和脱敏思路，但不为了新需求提前大规模重构。
- `semantic_models.py`、`semantic_query_projection.py`、`semantic_cache.py`、`semantic_payload_store.py`：通用检索只读引用语义状态、payload ref、cache key、recognition run id、model profile 和 prompt version，不触发识别。
- `candidate_review.py` / `relation_repository.py`：通用检索只读候选状态，不审核、不提升、不删除候选。
- CLI / HTTP / MCP adapter：首阶段不改；后续产品助手成熟后再新增产品级入口。

### 11.4 数据模型变化

首版不改变 Neo4j 数据模型：

- 不新增 Neo4j 节点标签。
- 不新增图谱关系类型。
- 不修改 schema 约束或索引。
- 不创建 `RecognitionRun` 图谱节点。
- 不设置或推断 `DrawingBlock.block_type`。

变化集中在产品层 DTO：

- `AssistantScope`：统一 project、drawing set、page、block、element、cross section、table、table caption、claim 等稳定业务 ID。
- `EvidenceRequirement`：表达所需证据类型、目标 scope、是否必需、最低状态、时效策略、是否允许模型生成、是否展开 payload。
- `RetrievalPlan` / `RetrievalStep`：表达只读查询计划、facade 方法白名单、参数、limit、依赖和需求来源。
- `EvidenceItem`：统一证据载体，保留 `fact_kind`、status、scope、value、source call、bbox、payload ref、recognition run id、model profile、prompt version、rule version 和 evidence refs。
- `RetrievalBundle`：按 `source_facts`、`derived_relations`、`semantic_observations`、`semantic_interpretations`、`candidate_relations`、`formal_relations`、`diagnostics`、`missing_evidence`、`warnings`、`source_calls` 分层输出。

首版合同版本建议：

- `contract_version = "drawing-assistant-contract-v1"`
- `retrieval_contract_version = "drawing-assistant-retrieval-v1"`

### 11.5 API 设计

首版只设计内部 Python API，不新增 HTTP/MCP 外部 API。

核心内部 API：

```text
RetrievalPlanner.plan(question_result, policy) -> RetrievalPlan
RetrievalExecutor.execute(plan, facade) -> RawRetrievalResult + SourceCallRecord[]
RetrievalBundleBuilder.build(question_result, plan, raw_result, source_calls) -> RetrievalBundle
GraphRetrievalService.retrieve(question_result, policy) -> RetrievalBundle
```

通用检索允许调用的 facade 白名单：

- `list_drawing_sets`
- `list_pages`
- `get_page_source_facts`
- `get_block_trace`
- `get_block_relations`
- `list_text_observations`
- `list_interpretations`
- `get_semantic_payload`
- `list_candidate_relations`
- `list_section_matches`

通用检索不允许调用：

- `recognize_page_semantics`
- `review_candidate_relation`
- `match_section_caption(..., write_back=True)`
- repository、Neo4j driver、session、Cypher 或 CLI 脚本。

后续外部 API 可单独设计为：

- `scripts/drawing_graph_assistant.py ask`
- `POST /api/v1/drawing-assistant/ask`
- MCP 产品级只读 assistant tool

但这些不属于首阶段交付范围。

### 11.6 异常处理

通用检索闭环使用稳定错误分类：

| 分类 | 含义 |
|---|---|
| `invalid_request` | 请求结构无效 |
| `scope_missing` | 必需 scope 缺失 |
| `scope_conflict` | 多个 scope 冲突 |
| `unsupported_evidence_type` | 无受控查询能力 |
| `target_not_found` | 目标业务 ID 不存在 |
| `empty_result` | 查询成功但无结果 |
| `facade_call_failed` | facade 调用失败 |
| `payload_unavailable` | payload 缺失或不可读 |
| `result_truncated` | 结果超过 limit |
| `internal_error` | 未预期错误 |

处理规则：

- required step 失败时，`RetrievalBundle.status` 至少为 `partial` 或 `error`。
- optional step 失败时，保留已成功证据并写 warning。
- 空结果写入 `missing_evidence`，不伪装成基础设施故障。
- payload 不可用时保留摘要和引用。
- 错误输出必须脱敏，不返回 traceback、Neo4j 密码、API key、token、Cypher 或 driver/session 对象。

### 11.7 安全方案

安全方案围绕只读、分层、脱敏和边界测试：

- **只读边界**：通用检索不写 Neo4j、不创建 `RecognitionRun`、不触发 Qwen、不审核候选、不提升正式关系。
- **`write_back=false` 默认**：即使未来上游请求允许写回，通用检索模块也不得消费写回授权。
- **事实分层保护**：`candidate_relation` 不能满足 `formal_relation`，`semantic_interpretation` 不能冒充 `source_fact`，`matched_candidate` 不能当作正式图谱关系。
- **依赖边界保护**：产品合同不得依赖 Neo4j、repository、HTTP、MCP、Qwen；通用检索不得导入 driver、repository、Cypher、CLI 脚本。
- **输入校验**：scope 只接受稳定业务 ID，不接受 Neo4j 内部 ID、Cypher 或自由查询。
- **数据最小化**：默认不读取 payload，页面级集合必须 limit 或分页，诊断只返回分类原因。
- **兼容安全**：现有 HTTP 仍默认 loopback，MCP 仍为本机 STDIO，QAService 仍拒绝 `write_back=true`。

### 11.8 设计结论

技术方案应采用“公共合同 + 独立通用检索服务”的分阶段路线。它能最大限度复用现有 `DrawingGraphToolFacade`、语义投影、候选关系查询和 QA 边界，同时为后续完整 `DrawingAssistantService` 提供稳定输入输出。该方案避免对现有 QA、HTTP、MCP 做无意义重构，也避免在 adapter 层堆积产品业务逻辑。
