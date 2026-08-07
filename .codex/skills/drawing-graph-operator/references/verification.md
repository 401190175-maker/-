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

## 4. Skill 校验

Skill 创建或修改后，运行 `quick_validate.py` 校验文件结构和 frontmatter：

```powershell
python <skill-creator-path>\scripts\quick_validate.py .codex\skills\drawing-graph-operator
```

其中 `<skill-creator-path>` 是本机 skill-creator 所在路径；如果该工具不可用，记录具体原因，并用等价静态检查（结构、frontmatter、必选字段）替代。

## 5. 报告状态清单

最终验证报告必须逐项给出状态，可选值：`未运行`、`单元测试通过`、`集成测试跳过`、`live Neo4j 已验证`、`live Neo4j 未验证`。不得把计划中的验证写成已经执行。
