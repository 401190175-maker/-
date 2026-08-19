# 验证规则

## 1. 基础回归命令

在项目根目录运行完整单元测试回归：

```powershell
python -m unittest discover tests -v
```

该命令不连接真实 Neo4j。集成测试位于 `tests/integration/`，在缺少真实连接配置时会被跳过。

## 2. 真实 Neo4j 集成测试环境变量

运行 live Neo4j 集成测试前，必须显式提供以下环境变量：

```powershell
$env:NEO4J_TEST_URI = "<neo4j-test-uri>"
$env:NEO4J_TEST_USER = "<neo4j-test-user>"
$env:NEO4J_TEST_PASSWORD = "<neo4j-test-password>"
```

这些值来自用户环境，不写入 Skill、不写入仓库文件。

## 3. skipped 不等于 live 通过

- 集成测试因环境变量缺失而跳过，**不等于** live Neo4j 已通过。
- 任何最终报告不得把 skipped 集成测试描述为已通过的 live 验证。
- 未运行、单元测试通过、集成测试跳过、live Neo4j 已验证、live Neo4j 未验证必须在报告中明确分开。

## 4. MCP 与 Skill 分层验证

第三阶段新增的证据必须按层分别报告，任何一层都不能替代另一层：

| 证据 | 可证明 | 不可证明 |
|---|---|---|
| 模型/工具单元测试 | 输入白名单、领域转换、单次 `ask()`、成功/错误映射 | 真实数据库可用性 |
| MCP in-memory 合约测试 | initialize、tools/list、tools/call、Schema、annotations、isError | 真实 STDIO 子进程链路 |
| STDIO smoke | 子进程握手、工具发现、一次 fake 调用、stdout 纯净 | live Neo4j 数据正确性 |
| Skill 发现/触发测试 | 权威路径发现、显式/隐式触发、工具路由 | MCP server 已连接真实库 |
| HTTP 回归 | 第二阶段兼容性 | MCP transport 可用性 |
| live Neo4j 集成 | 真实测试库链路 | 生产环境安全与容量 |
| 产品三入口 fake 验收 | 产品 CLI、HTTP、MCP 共用 `AnswerPackage` 合同与只读边界 | MCP 宿主注册或 live Neo4j 正确性 |

- fake runtime、HTTP health 和 STDIO smoke 都不能证明 live Neo4j。
- MCP in-memory 测试不能替代 STDIO smoke；STDIO fake smoke 不能替代
  live Neo4j 集成；HTTP TestClient 不能替代 MCP session。
- 产品 CLI、产品 HTTP TestClient 与产品 MCP in-memory 都不能相互冒充；必须分别
  报告入口、transport 和 live 数据库状态。
- skipped 继续标为 live Neo4j 未验证，不得计入 passed。

## 5. Skill 校验

Skill 创建或修改后，运行 `quick_validate.py` 校验文件结构和 frontmatter：

```powershell
python <skill-creator-path>\scripts\quick_validate.py .codex\skills\drawing-graph-operator
```

其中 `<skill-creator-path>` 是本机 skill-creator 所在路径；如果该工具不可用，记录具体原因，并用等价静态检查（结构、frontmatter、必选字段）替代。

## 6. 报告状态清单

最终验证报告必须逐项给出状态，可选值：`未运行`、`单元测试通过`、`集成测试跳过`、`live Neo4j 已验证`、`live Neo4j 未验证`。不得把计划中的验证写成已经执行。
