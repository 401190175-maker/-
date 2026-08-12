# 产品公共合同与通用检索闭环实施任务

**文档状态：** 实施任务计划  
**日期：** 2026-08-11  
**依据文档：** `proposal.md`、`design.md`、`Feature_Analysis_Report.md`  
**总目标：** 在不重构现有 QA/HTTP/MCP 的前提下，新增产品公共合同与只读通用检索闭环，为后续 `DrawingAssistantService` 提供稳定基础。

## 全局约束

- 优先复用已有 `DrawingGraphToolFacade`、Tool DTO、语义投影、QA 边界和序列化经验。
- 禁止无意义重构；不删除、不替换现有 `DrawingGraphQAService`、QA CLI、HTTP API、MCP adapter。
- 通用检索首版只读，不调用 Qwen，不创建 `RecognitionRun`，不写 Neo4j，不审核或提升候选关系。
- 默认 `write_back=false`；通用检索模块不得消费写回授权。
- 候选关系、`matched_candidate`、语义解释不得冒充正式事实或来源事实。
- 产品合同和通用检索模块不得导入 Neo4j driver、repository、Cypher、HTTP/FastAPI、MCP SDK、Qwen/DashScope 客户端或 CLI 脚本。
- 每个任务完成后运行该任务指定测试；skipped live Neo4j 集成测试不得报告为通过。

## 任务总览

1. 产品合同基础枚举与版本
2. 产品 scope 与请求合同
3. 问题理解结果合同
4. 证据需求与检索策略合同
5. 检索计划合同
6. 统一证据与检索结果合同
7. 答案、追溯与反馈公共合同
8. 检索规划 scope 校验
9. 来源事实检索规划
10. 关系与语义证据检索规划
11. 检索计划去重、payload 与 limit 策略
12. 检索执行 facade 白名单
13. 检索执行成功调用与 source call 记录
14. 检索执行异常分类与脱敏
15. 来源事实归一化
16. 关系、语义和候选证据归一化
17. 缺失证据、warning 与 bundle 状态汇总
18. 通用检索服务编排
19. 现有六类 QA 到产品检索需求的兼容映射
20. 架构边界静态测试
21. 文档同步

---

## Task 1：产品合同基础枚举与版本

**目标：** 建立产品公共合同的版本常量和基础枚举，后续所有 DTO 复用同一事实类型、状态和原因码，不再各模块重复定义。

**修改文件：**

- 新建：`src/drawing_graph/assistant_models.py`
- 新建：`tests/test_assistant_models_contract.py`

**独立测试：**

```powershell
python -m unittest tests.test_assistant_models_contract -v
```

**完成标准：**

- `assistant_models.py` 定义 `CONTRACT_VERSION = "drawing-assistant-contract-v1"`。
- 定义 `RETRIEVAL_CONTRACT_VERSION = "drawing-assistant-retrieval-v1"`。
- 定义 `FactKind`，至少包含 `source_fact`、`derived_relation`、`semantic_observation`、`semantic_interpretation`、`candidate_relation`、`formal_relation`、`diagnostic`、`unsupported`。
- 定义 `RetrievalStatus`，至少包含 `ok`、`partial`、`error`、`unsupported`、`clarification_required`。
- 定义 `EvidenceType`，至少覆盖项目图纸册、图纸册页面、页面来源事实、图块追溯、图块派生关系、文字观察、结构化解释、语义 payload、候选关系、断面匹配。
- 定义 `ReasonCode`，至少包含 `scope_missing`、`scope_conflict`、`unsupported_evidence_type`、`target_not_found`、`empty_result`、`facade_call_failed`、`payload_unavailable`、`result_truncated`。
- 测试验证枚举值为稳定字符串，合同版本常量不为空且等于设计文档指定值。

---

## Task 2：产品 scope 与请求合同

**目标：** 定义产品层请求范围和请求 DTO，使后续问题理解、检索、融合、答案都使用同一 `request_id` 与稳定业务 ID。

**修改文件：**

- 修改：`src/drawing_graph/assistant_models.py`
- 修改：`tests/test_assistant_models_contract.py`

**独立测试：**

```powershell
python -m unittest tests.test_assistant_models_contract -v
```

**完成标准：**

- 定义 `AssistantScope`，字段包含 `project_id`、`drawing_set_id`、`page_id`、`block_id`、`element_id`、`cross_section_id`、`table_id`、`table_caption_id`、`claim_id`，默认均为 `None`。
- 定义 `AssistantRequest`，字段包含 `request_id`、`question`、`conversation_context`、`scope_hint`、`language`、`allow_recognition`、`allow_write_back`、`answer_format`。
- `AssistantRequest.allow_write_back` 默认值为 `False`。
- `AssistantRequest.allow_recognition` 默认值为 `True`。
- `AssistantRequest.language` 默认值为 `zh-CN`。
- 测试验证默认值、scope 序列化、空 scope 可构造、`allow_write_back` 不会因问题文本自动变成 `True`。

---

## Task 3：问题理解结果合同

**目标：** 定义 `QuestionUnderstandingResult` 和子请求 DTO，使后续检索规划可以稳定消费问题类型、scope 和证据需求。

**修改文件：**

- 修改：`src/drawing_graph/assistant_models.py`
- 修改：`tests/test_assistant_models_contract.py`

**独立测试：**

```powershell
python -m unittest tests.test_assistant_models_contract -v
```

**完成标准：**

- 定义 `AssistantSubrequest`，字段包含 `subrequest_id`、`question_type`、`scope`、`required_evidence`、`answer_requirements`、`confidence`、`ambiguities`、`unsupported_parts`。
- 定义 `QuestionUnderstandingResult`，字段包含 `request_id`、`question_type`、`scope`、`required_evidence`、`subrequests`、`answer_requirements`、`confidence`、`ambiguities`、`unsupported_parts`。
- 单意图请求允许 `subrequests=[]`。
- 多意图子请求必须保留父 `request_id` 可追溯关系，至少通过 `QuestionUnderstandingResult.request_id` 和子请求 `subrequest_id` 表达。
- 测试验证单意图、多意图、歧义和 unsupported_parts 的默认集合互不共享可变对象。

---

## Task 4：证据需求与检索策略合同

**目标：** 定义 `EvidenceRequirement` 与 `RetrievalPolicy`，明确“需要什么证据”和检索阶段的 limit、payload、状态要求。

**修改文件：**

- 修改：`src/drawing_graph/assistant_models.py`
- 修改：`tests/test_assistant_models_contract.py`

**独立测试：**

```powershell
python -m unittest tests.test_assistant_models_contract -v
```

**完成标准：**

- 定义 `FreshnessPolicy`，至少支持 `any`、`current_image`、`current_prompt`、`current_contract`。
- 定义 `EvidenceRequirement`，字段包含 `requirement_id`、`evidence_type`、`target_scope`、`required`、`minimum_status`、`freshness_policy`、`allow_model_generation`、`include_payload`、`limit`。
- `EvidenceRequirement.required` 默认 `True`。
- `EvidenceRequirement.include_payload` 默认 `False`。
- `EvidenceRequirement.allow_model_generation` 默认 `False`，且注释或字段说明明确它不代表允许写数据库。
- 定义 `RetrievalPolicy`，字段包含 `default_limit`、`max_limit`、`include_payload_by_default`。
- 测试验证默认不展开 payload、limit 不超过 `max_limit` 的约束由后续 planner 使用、模型生成授权不改变 `allow_write_back`。

---

## Task 5：检索计划合同

**目标：** 定义只读检索计划 DTO，使 planner 可以输出可执行、可审计、可去重的查询步骤。

**修改文件：**

- 修改：`src/drawing_graph/assistant_models.py`
- 修改：`tests/test_assistant_models_contract.py`

**独立测试：**

```powershell
python -m unittest tests.test_assistant_models_contract -v
```

**完成标准：**

- 定义 `RetrievalStep`，字段包含 `step_id`、`facade_method`、`scope`、`parameters`、`required`、`depends_on`、`limit`、`include_payload`、`requirement_ids`、`dedupe_key`。
- 定义 `RetrievalPlan`，字段包含 `request_id`、`subrequest_id`、`steps`、`dedupe_keys`、`warnings`。
- 定义 `SourceCallRecord`，字段包含 `source_call_id`、`step_id`、`facade_method`、`status`、`reason_code`、`result_count`、`warning`。
- 测试验证 `RetrievalStep.parameters` 不包含敏感字段示例时可正常序列化，但敏感字段检查留给后续边界测试。
- 测试验证 `depends_on`、`requirement_ids`、`warnings` 默认空列表互不共享。

---

## Task 6：统一证据与检索结果合同

**目标：** 定义 `EvidenceItem`、`MissingEvidence` 和 `RetrievalBundle`，保证所有检索结果按事实层级统一输出。

**修改文件：**

- 修改：`src/drawing_graph/assistant_models.py`
- 修改：`tests/test_assistant_models_contract.py`

**独立测试：**

```powershell
python -m unittest tests.test_assistant_models_contract -v
```

**完成标准：**

- 定义 `EvidenceRef` 或复用产品层独立 `AssistantEvidenceRef`，字段至少包含 `project_id`、`drawing_set_id`、`page_id`、`block_id`、`element_id`、`bbox`、`recognition_run_id`、`payload_ref`、`rule_version`。
- 定义 `EvidenceItem`，字段包含 `evidence_id`、`fact_kind`、`status`、`scope`、`value`、`confidence`、`source_system`、`source_call_id`、`recognition_run_id`、`payload_ref`、`model_profile`、`prompt_version`、`rule_version`、`created_at_or_version`、`evidence_refs`。
- 定义 `MissingEvidence`，字段包含 `requirement_id`、`evidence_type`、`target_scope`、`reason_code`、`message`。
- 定义 `RetrievalBundle`，字段包含 `request_id`、`subrequest_id`、`scope`、`source_facts`、`derived_relations`、`semantic_observations`、`semantic_interpretations`、`candidate_relations`、`formal_relations`、`diagnostics`、`missing_evidence`、`warnings`、`source_calls`、`status`。
- 测试验证 candidate 证据只能放入 `candidate_relations` 示例集合，formal 证据只能放入 `formal_relations` 示例集合。

---

## Task 7：答案、追溯与反馈公共合同

**目标：** 为后续完整产品闭环预留稳定答案、claim、trace 和 feedback DTO，但不实现答案生成或反馈写回逻辑。

**修改文件：**

- 修改：`src/drawing_graph/assistant_models.py`
- 修改：`tests/test_assistant_models_contract.py`

**独立测试：**

```powershell
python -m unittest tests.test_assistant_models_contract -v
```

**完成标准：**

- 定义 `Claim`，字段包含 `claim_id`、`statement`、`claim_type`、`status`、`confidence`、`evidence_ids`、`fact_kinds`、`scope`、`qualifiers`。
- 定义 `Citation`，字段至少包含 `page_id`、`block_id`、`element_id`、`bbox`、`observation_id`、`interpretation_id`、`candidate_group_id`、`recognition_run_id`、`payload_ref`、`rule_version`。
- 定义 `AnswerPackage`，字段包含 `request_id`、`question_type`、`scope`、`status`、`machine_answer`、`text_answer`、`claims`、`citations`、`warnings`、`unsupported_parts`、`recognition_run_ids`、`follow_up_actions`。
- 定义 `TraceRecord`，字段包含 `request_id`、`question`、`question_type`、`scope`、`module_events`、`retrieval_calls`、`recognition_run_ids`、`evidence_ids`、`claim_ids`、`answer_status`。
- 定义 `FeedbackEvent`，字段包含 `feedback_id`、`request_id`、`claim_id`、`action`、`reason`、`correction`、`user_id`、`created_at`。
- 测试验证这些 DTO 只承载数据，不触发任何写回或外部调用。

---

## Task 8：检索规划 scope 校验

**目标：** 新增检索规划器的 scope 校验能力，缺失或冲突 scope 以稳定 missing evidence/diagnostic 表达。

**修改文件：**

- 新建：`src/drawing_graph/assistant_retrieval_planner.py`
- 新建：`tests/test_assistant_retrieval_planner.py`

**独立测试：**

```powershell
python -m unittest tests.test_assistant_retrieval_planner -v
```

**完成标准：**

- 定义 `RetrievalPlanner.plan(question_result, policy) -> RetrievalPlan`。
- 当必需证据需求缺少目标 scope 时，生成无 facade 调用的 plan warning 或 unsupported step，reason code 为 `scope_missing`。
- 当同一需求出现冲突 scope 时，reason code 为 `scope_conflict`。
- scope 校验不访问 facade、不导入 `tool_facade.py`。
- 测试覆盖缺少 `page_id` 的页面来源事实需求、缺少 `block_id` 的图块追溯需求、同一需求同时给出冲突 page/block 目标的场景。

---

## Task 9：来源事实检索规划

**目标：** 将来源事实类 `EvidenceRequirement` 映射为现有 facade 只读方法。

**修改文件：**

- 修改：`src/drawing_graph/assistant_retrieval_planner.py`
- 修改：`tests/test_assistant_retrieval_planner.py`

**独立测试：**

```powershell
python -m unittest tests.test_assistant_retrieval_planner -v
```

**完成标准：**

- 项目图纸册需求映射到 `list_drawing_sets(project_id, limit)`。
- 图纸册页面需求映射到 `list_pages(drawing_set_id, limit)`。
- 页面来源事实需求映射到 `get_page_source_facts(page_id, element_types=None, include_image_meta=True)`。
- 图块位置追溯需求映射到 `get_block_trace(block_id)`。
- 生成的 `RetrievalStep.facade_method` 只使用设计白名单中的方法名。
- 测试验证每类来源事实需求生成一个 required step，并携带对应 `requirement_id`。

---

## Task 10：关系与语义证据检索规划

**目标：** 将派生关系、语义观察、语义解释、payload、候选关系和断面匹配需求映射为现有 facade 只读方法。

**修改文件：**

- 修改：`src/drawing_graph/assistant_retrieval_planner.py`
- 修改：`tests/test_assistant_retrieval_planner.py`

**独立测试：**

```powershell
python -m unittest tests.test_assistant_retrieval_planner -v
```

**完成标准：**

- 图块派生关系需求映射到 `get_block_relations(block_id)`。
- 文字观察需求映射到 `list_text_observations(...)`。
- 结构化解释需求映射到 `list_interpretations(...)`。
- 完整语义 payload 需求仅在 `include_payload=True` 时映射到 `get_semantic_payload(payload_ref)`。
- 候选关系需求映射到 `list_candidate_relations(page_id=None, block_id=None, relation_type=None, status=None)`。
- 断面匹配关系需求映射到 `list_section_matches(cross_section_id=None, page_id=None, statuses=None)`。
- 不生成 `recognize_page_semantics`、`review_candidate_relation` 或 `match_section_caption` step。
- 测试验证上述禁止方法不会出现在任何 plan step 中。

---

## Task 11：检索计划去重、payload 与 limit 策略

**目标：** 在 planner 中实现同请求内查询去重、payload 默认关闭和 limit 上限策略，控制性能和数据最小化。

**修改文件：**

- 修改：`src/drawing_graph/assistant_retrieval_planner.py`
- 修改：`tests/test_assistant_retrieval_planner.py`

**独立测试：**

```powershell
python -m unittest tests.test_assistant_retrieval_planner -v
```

**完成标准：**

- 相同 facade 方法、scope 和参数的多个需求合并为一个 `RetrievalStep`。
- 合并后的 step 保留全部 `requirement_ids`。
- `RetrievalPolicy.max_limit` 能限制每个 step 的 `limit`。
- `include_payload` 默认 `False`，只有需求显式要求时才为 `True`。
- `RetrievalPlan.dedupe_keys` 包含每个合并查询的稳定 key。
- 测试覆盖两个相同页面来源事实需求被合并、payload 默认关闭、超过 max limit 被压到 max limit。

---

## Task 12：检索执行 facade 白名单

**目标：** 新增检索执行器的 facade 方法白名单，确保通用检索不能调用识别、写回、审核或底层仓储能力。

**修改文件：**

- 新建：`src/drawing_graph/assistant_retrieval_executor.py`
- 新建：`tests/test_assistant_retrieval_executor.py`

**独立测试：**

```powershell
python -m unittest tests.test_assistant_retrieval_executor -v
```

**完成标准：**

- 定义 `RetrievalExecutor.execute(plan, facade)`。
- 白名单只包含 `list_drawing_sets`、`list_pages`、`get_page_source_facts`、`get_block_trace`、`get_block_relations`、`list_text_observations`、`list_interpretations`、`get_semantic_payload`、`list_candidate_relations`、`list_section_matches`。
- 遇到非白名单 `facade_method` 时不调用 facade，返回 `SourceCallRecord.status="error"`，reason code 为 `unsupported_evidence_type`。
- 测试使用 fake facade 验证 `recognize_page_semantics`、`review_candidate_relation`、`match_section_caption` 不会被调用。

---

## Task 13：检索执行成功调用与 source call 记录

**目标：** 实现 executor 对白名单 facade 方法的成功调用和 `SourceCallRecord` 记录。

**修改文件：**

- 修改：`src/drawing_graph/assistant_retrieval_executor.py`
- 修改：`tests/test_assistant_retrieval_executor.py`

**独立测试：**

```powershell
python -m unittest tests.test_assistant_retrieval_executor -v
```

**完成标准：**

- fake facade 的白名单方法可被 executor 调用。
- executor 返回 raw result 时保留 `step_id` 与原始返回对象的映射。
- 每次成功调用生成 `SourceCallRecord`，包含 `source_call_id`、`step_id`、`facade_method`、`status="ok"`、`result_count`。
- 同一个 `dedupe_key` 的 step 在一次执行中只调用一次 facade。
- 测试覆盖 `get_page_source_facts`、`get_block_trace`、`list_candidate_relations` 三类成功调用。

---

## Task 14：检索执行异常分类与脱敏

**目标：** 将 facade 调用异常转换为稳定错误记录，并防止 traceback、Cypher、密码、token 等敏感信息进入结果。

**修改文件：**

- 修改：`src/drawing_graph/assistant_retrieval_executor.py`
- 修改：`tests/test_assistant_retrieval_executor.py`

**独立测试：**

```powershell
python -m unittest tests.test_assistant_retrieval_executor -v
```

**完成标准：**

- required step facade 异常生成 `SourceCallRecord.status="error"`，reason code 为 `facade_call_failed`。
- optional step facade 异常生成 warning，但不阻断其他 step。
- 错误消息经过脱敏，不包含 `password`、`token`、`Authorization`、`MATCH (`、`Traceback`。
- payload 读取失败可标记为 `payload_unavailable`。
- 测试覆盖 required 异常、optional 异常、敏感信息脱敏、payload 不可用分类。

---

## Task 15：来源事实归一化

**目标：** 新增检索结果归一化器，把来源事实类 facade DTO 转为 `EvidenceItem` 和 `RetrievalBundle.source_facts`。

**修改文件：**

- 新建：`src/drawing_graph/assistant_retrieval_projection.py`
- 新建：`tests/test_assistant_retrieval_projection.py`

**独立测试：**

```powershell
python -m unittest tests.test_assistant_retrieval_projection -v
```

**完成标准：**

- 定义 `RetrievalBundleBuilder.build(question_result, plan, raw_result, source_calls) -> RetrievalBundle`。
- `list_drawing_sets`、`list_pages`、`get_page_source_facts`、`get_block_trace` 的结果映射为 `FactKind.SOURCE_FACT`。
- 每个 `EvidenceItem` 具有稳定 `evidence_id`、`scope`、`source_call_id` 和 `evidence_refs`。
- bbox 以 `{x_min, y_min, x_max, y_max}` 字典或现有 DTO 等价结构保留。
- 测试覆盖页面来源事实和图块追溯的归一化。

---

## Task 16：关系、语义和候选证据归一化

**目标：** 将派生关系、语义观察、语义解释、候选关系和正式关系分别归入正确事实层级。

**修改文件：**

- 修改：`src/drawing_graph/assistant_retrieval_projection.py`
- 修改：`tests/test_assistant_retrieval_projection.py`

**独立测试：**

```powershell
python -m unittest tests.test_assistant_retrieval_projection -v
```

**完成标准：**

- `get_block_relations` 中正式 caption/basic info/annotation/section mark 信息映射为 `derived_relation` 或 `formal_relation`，候选 ID 映射为 `candidate_relation`。
- `list_text_observations` 结果映射为 `semantic_observation`。
- `list_interpretations` 结果映射为 `semantic_interpretation`。
- `list_candidate_relations` 结果始终映射为 `candidate_relation`。
- `list_section_matches` 的 candidate 状态映射为 `candidate_relation`，confirmed/formal 状态映射为 `formal_relation`。
- 测试验证 candidate 不会进入 `formal_relations`，semantic interpretation 不会进入 `source_facts`。

---

## Task 17：缺失证据、warning 与 bundle 状态汇总

**目标：** 在 `RetrievalBundleBuilder` 中汇总空结果、缺失证据、截断、可选失败和整体状态。

**修改文件：**

- 修改：`src/drawing_graph/assistant_retrieval_projection.py`
- 修改：`tests/test_assistant_retrieval_projection.py`

**独立测试：**

```powershell
python -m unittest tests.test_assistant_retrieval_projection -v
```

**完成标准：**

- 空结果生成 `MissingEvidence`，reason code 为 `empty_result`。
- unsupported step 生成 `MissingEvidence`，reason code 为 `unsupported_evidence_type`。
- required source call 失败时 `RetrievalBundle.status` 为 `error` 或 `partial`。
- 只有 optional source call 失败且存在其他证据时，`RetrievalBundle.status` 为 `partial`。
- result_count 超过 limit 或 executor 标记截断时写入 `warnings`，reason code 为 `result_truncated`。
- 测试覆盖 empty、unsupported、required failure、optional failure 和 truncated 五类场景。

---

## Task 18：通用检索服务编排

**目标：** 新增 `GraphRetrievalService`，串联 planner、executor、bundle builder，形成完整只读检索闭环入口。

**修改文件：**

- 新建：`src/drawing_graph/assistant_retrieval_service.py`
- 新建：`tests/test_assistant_retrieval_service.py`

**独立测试：**

```powershell
python -m unittest tests.test_assistant_retrieval_service -v
```

**完成标准：**

- 定义 `GraphRetrievalService(facade, planner=None, executor=None, bundle_builder=None)`。
- 定义 `retrieve(question_result, policy=None) -> RetrievalBundle`。
- 默认装配 `RetrievalPlanner`、`RetrievalExecutor`、`RetrievalBundleBuilder`。
- fake facade 下可完成 `QuestionUnderstandingResult -> RetrievalPlan -> facade call -> RetrievalBundle`。
- 服务不导入 Neo4j driver、不创建 driver、不读取环境变量。
- 测试验证服务编排顺序、默认依赖、fake facade 输出和无写回调用。

---

## Task 19：现有六类 QA 到产品检索需求的兼容映射

**目标：** 为现有六类固定 QA 提供产品检索需求映射，便于后续复用通用检索闭环，同时不改造 `DrawingGraphQAService`。

**修改文件：**

- 新建：`src/drawing_graph/assistant_qa_mapping.py`
- 新建：`tests/test_assistant_qa_mapping.py`

**独立测试：**

```powershell
python -m unittest tests.test_assistant_qa_mapping -v
```

**完成标准：**

- 定义 `qa_request_to_question_result(request: QARequest) -> QuestionUnderstandingResult`。
- `page_summary` 映射为页面来源事实、文字观察、结构化解释的证据需求。
- `block_relations` 映射为图块追溯和图块派生关系证据需求。
- `candidate_relations` 映射为候选关系证据需求。
- `section_matches` 映射为断面匹配关系证据需求。
- `table_caption_status` 映射为页面来源事实或表格/表题相关证据需求。
- `diagnostic_status` 映射为诊断、来源事实和已有关系状态需求。
- 该 mapper 不修改 `qa_service.py` 行为，不让 `qa_service.py` 依赖产品检索模块。

---

## Task 20：架构边界静态测试

**目标：** 用静态测试保护产品公共合同与通用检索模块的依赖边界，防止绕过 facade 或引入写回能力。

**修改文件：**

- 新建：`tests/test_assistant_retrieval_boundaries.py`

**独立测试：**

```powershell
python -m unittest tests.test_assistant_retrieval_boundaries -v
```

**完成标准：**

- 测试扫描 `src/drawing_graph/assistant_*.py`。
- 禁止出现 `neo4j`、`GraphDatabase`、`session`、`transaction`、`MATCH `、`MERGE `、`CREATE `、`RelationRepository`、`Neo4jRepository`、`SemanticNeo4jRepository`、`CandidateReviewService` 写回调用、`scripts.import_json`、`scripts.enrich_block_relations`、`scripts.review_candidate_relations`。
- 允许 `assistant_qa_mapping.py` 导入 `qa_models.py`，但不允许 `qa_service.py` 反向导入 `assistant_` 模块。
- 测试验证通用检索模块源码中不出现 `recognize_page_semantics(`、`review_candidate_relation(`、`write_back=True`。
- 完成后该测试能独立通过。

---

## Task 21：文档同步

**目标：** 将产品公共合同与通用检索闭环的实际新增模块、接口、数据变化和架构边界同步到维护文档，但不宣称未实现能力。

**修改文件：**

- 修改：`Module.md`
- 修改：`architecture.md`
- 修改：`README.md`
- 修改：`changes/产品实现层/产品公共合同与通用检索闭环/design.md`
- 修改：`changes/产品实现层/产品公共合同与通用检索闭环/Feature_Analysis_Report.md`
- 新建或修改：`tests/test_assistant_docs.py`

**独立测试：**

```powershell
python -m unittest tests.test_assistant_docs -v
```

**完成标准：**

- `Module.md` 增加产品公共合同模块、通用检索规划、执行、归一化、服务编排的职责记录。
- `architecture.md` 增加产品层并列链路，但保留现有 QA/HTTP/MCP 链路不变。
- `README.md` 只说明该能力的只读边界和验证方式，不把完整 `DrawingAssistantService`、外部 HTTP/MCP 产品入口、Qwen live、Neo4j 写回说成已完成。
- 目标目录 `design.md` 和 `Feature_Analysis_Report.md` 与实际模块命名一致。
- 文档测试验证关键边界语句存在：默认只读、`write_back=false`、不调用 Qwen、不创建 `RecognitionRun`、不写 Neo4j、候选不是正式事实、skipped live 测试不等于通过。

---

## 整体验证建议

完成全部任务后运行：

```powershell
python -m unittest tests.test_assistant_models_contract -v
python -m unittest tests.test_assistant_retrieval_planner -v
python -m unittest tests.test_assistant_retrieval_executor -v
python -m unittest tests.test_assistant_retrieval_projection -v
python -m unittest tests.test_assistant_retrieval_service -v
python -m unittest tests.test_assistant_qa_mapping -v
python -m unittest tests.test_assistant_retrieval_boundaries -v
python -m unittest tests.test_assistant_docs -v
```

可选全量回归：

```powershell
python -m unittest discover tests -v
```

如果未设置 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD`，集成测试跳过是预期行为，但不能报告为 live Neo4j 已通过。
