# 产品级 Skill 测试入口与路由

本资料只定义 Codex 如何通过产品级只读入口测试图块图谱问答链路。Skill 仍是 facade 外侧的操作策略层，负责选择入口、组织测试和报告验证状态；不实现业务逻辑、不连接数据库、不保存密钥、不直接调用 repository、Neo4j driver 或 Cypher。

## 1. 入口定位

产品级自然语言问答测试的目标链路是：

```text
Codex Skill
  -> 产品 MCP 工具 ask_drawing_assistant（首选）或产品只读 CLI scripts/drawing_assistant.py（后备）
  -> DrawingAssistantService.answer()
  -> QuestionUnderstandingService / GraphRetrievalService / SemanticGapDecisionService
  -> DrawingGraphToolFacade.recognize_semantic_targets(write_back=false)
  -> EvidenceFusionService(write_back_policy=None)
  -> AnswerGenerationService
  -> AnswerPackage
```

产品 MCP server 为本地 STDIO 只读入口，启动脚本是 `scripts/serve_drawing_assistant_mcp.py`，唯一工具是 `ask_drawing_assistant`。产品 CLI 是 `scripts/drawing_assistant.py`。产品 HTTP adapter 是同级只读入口，可用于 HTTP adapter 回归，但 Skill 测试自然语言问答时优先 MCP，其次 CLI。

## 2. 路由规则

| 测试意图 | 首选入口 | 后备入口 | 可证明 | 不可证明 |
|---|---|---|---|---|
| 用自然语言问图纸、图块、候选关系或诊断 | `ask_drawing_assistant` | `scripts/drawing_assistant.py` | 产品问答合同、只读路由、`AnswerPackage` 输出 | MCP 宿主已注册、live Neo4j 正确 |
| 验证产品 CLI 输出 envelope 或中文文本 | 产品 CLI | 无需 MCP 后备 | CLI 参数、退出码、脱敏和只读边界 | MCP transport 可用 |
| 验证产品 HTTP adapter | HTTP TestClient 或本地 socket | 不降级为 MCP/CLI | HTTP 协议、认证、超时和错误映射 | MCP transport 可用 |
| 验证产品 MCP adapter | MCP in-memory 或 STDIO smoke | 不降级为 HTTP | 工具 schema、一次工具调用、stdout 协议纯净 | live Neo4j 正确 |
| 验证 live Neo4j 产品链路 | 产品 MCP/CLI 加真实测试库环境 | 不自动降级 | 真实测试库读取链路 | 生产环境安全与容量 |

当问题可以由六个固定 QA 工具明确回答时，仍可按 `qa-workflows.md` 使用旧 QA 工具；当用户要测试完整产品自然语言链路、问题理解、答案生成、三入口一致性或 `DrawingAssistantService.answer()` 时，使用本资料。

## 3. 输入与安全边界

- 产品问答请求只接受自然语言 `question`、`request_id`、`language`、`scope_hint`、`allow_recognition` 和 `answer_format` 这类产品字段。
- 不接受 `write_back`、`allow_write_back`、Cypher、Neo4j 凭据、API key、文件路径、driver、session、repository 或底层对象字段。
- `allow_recognition=true` 只允许按需 dry-run 识别，不等于写回授权。
- 产品链路固定 `write_back=false`；07 拒绝问答写回，04 调用固定 `write_back=false`，05 调用固定 `write_back_policy=None`。
- `candidate_relation`、`CANDIDATE_*`、`matched_candidate` 和模型解释不等于 `formal_relation` 或来源事实。

## 4. 透明降级

- 已配置并可用时，优先调用产品 MCP 工具 `ask_drawing_assistant`。
- 产品 MCP 不可用、工具缺失、初始化失败或超时时，可以降级到 `scripts/drawing_assistant.py`，但必须说明 MCP 未成功使用的原因类别。
- 降级后只报告为 CLI 验证，不得写成 MCP 已验证。
- 降级时不得扩大 scope，不得自动触发写回、导入、离线增强、候选复核或正式关系提升。
- 产品 HTTP adapter 测试失败时，不用 CLI 或 MCP 冒充 HTTP 通过；各入口验证结果必须分层报告。

## 5. 推荐测试清单

离线/fake 回归：

```powershell
python -m unittest tests.test_drawing_assistant_cli tests.test_drawing_assistant_service tests.test_drawing_assistant_e2e -v
python -m unittest tests.test_assistant_mcp_models tests.test_assistant_mcp_tools tests.test_assistant_mcp_runtime tests.test_assistant_mcp_server tests.test_assistant_mcp_cli tests.test_assistant_mcp_boundaries -v
python -m unittest tests.test_product_adapter_e2e tests.test_product_adapter_qa_compatibility -v
```

文档与 Skill 契约：

```powershell
python -m unittest tests.test_skill_docs tests.test_qa_mcp_skill_behavior tests.test_assistant_adapter_docs -v
```

完整离线回归：

```powershell
python -m unittest discover tests -v
```

live Neo4j 产品链路验证必须由用户显式提供 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD` 或当前进程的真实测试库环境；这些值不得写入 Skill、仓库文件或测试报告正文。

## 6. 报告格式

最终报告必须分层写明：

- 产品 Skill 路由：未运行 / MCP 已调用 / CLI 降级已调用 / HTTP 已调用。
- 单元/合同测试：未运行 / 单元测试通过 / 失败。
- MCP in-memory：未运行 / 单元测试通过 / 失败。
- STDIO smoke：未运行 / 通过 / 失败。
- HTTP socket：未运行 / 通过 / 失败。
- live Neo4j：未运行 / live Neo4j 已验证 / live Neo4j 未验证 / 集成测试跳过。
- live DashScope 或真实文本 provider：未运行 / 已验证 / 未验证。

不得把 fake runtime、HTTP health、MCP in-memory、STDIO smoke 或 skipped 集成测试描述为 live Neo4j 已通过。
