# 失败封闭：入口不可用时的行为

## 1. 决策表

| 前置门报告 | 允许动作 |
|---|---|
| MCP 已注册且可用 | 使用 MCP；不降级 |
| MCP 不可用；Neo4j 环境齐全且连接成功 | 说明原因后透明降级到受控 CLI |
| MCP 不可用；Neo4j 环境缺失或连接失败 | BLOCKED：不查询、不识别、不自创入口 |
| 识别类请求需要 Qwen；provider=qwen 且 API key 已配置且用户授权 dry-run | 仅经受控入口 dry-run（write_back=false） |
| 上述条件不满足 | BLOCKED：列出缺失项（变量名，不打印值），询问用户 |
| 用户明确授权兜底（如 OCR） | 仅执行授权范围；输出标注“外部观察/兜底”，不得冒充项目语义证据层 |

## 2. BLOCKED 报告模板

```text
BLOCKED（入口不可用）
- 前置门报告：<引用 skill_preflight.py 输出>
- 缺失前置条件：<MCP 未注册 / NEO4J_URI 未配置 / Neo4j 连接失败 / DRAWING_GRAPH_RECOGNITION_PROVIDER 未设置…>
- 已尝试入口：<MCP / 受控 CLI / facade>
- 未执行：<查询、识别、写回均未执行>
- 所需授权：<配置 Neo4j 测试库 / 设置 provider / 明确授权兜底方案>
- 等待用户指示。
```

## 3. 禁止内容

- 不自动重试、不扩大范围、不静默降级；
- 不把 BLOCKED 当答案、不补造结论；
- 不打印密码、token、API key 或凭据 URI；
- 不写库、不提升候选关系。
