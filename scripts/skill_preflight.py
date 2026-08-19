"""skill_preflight.py -- 只读前置门检查（Preflight Gate）。

用法:
    python scripts\\skill_preflight.py [--config-path PATH] [--connect-timeout SECONDS]

本脚本只读取配置文件与环境变量，不写任何文件，不调用业务源码，不执行
任何 Cypher/查询/导入/识别。即使检查 Neo4j 端口，也只做 TCP 连通性探测，
不发送凭据、不建立业务连接。

输出: 单个 JSON 对象到 stdout；不输出任何密钥，密码、token、API key 或
凭据 URI 的真实值均不出现，环境变量只报告“是否已设置”的布尔值。

退出码:
    0 = 至少一个受控入口可用
    3 = 全部受控入口不可用（BLOCKED）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional


MCP_SERVER_NAMES = ("drawing-graph-qa", "drawing-assistant")
NEO4J_ENV_VARS = ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")
PROJECT_ENV_VARS = ("DRAWING_GRAPH_DATA_ROOT", "DRAWING_GRAPH_PROJECT_SLUG")
RECOGNITION_PROVIDER_VAR = "DRAWING_GRAPH_RECOGNITION_PROVIDER"
DASHSCOPE_KEY_VAR = "DASHSCOPE_API_KEY"
DEFAULT_BOLT_PORT = 7687


def _default_config_path(env: Mapping[str, str]) -> Path:
    """按 CODEX_HOME 或 USERPROFILE/HOME 解析 Codex config.toml 位置。"""

    codex_home = env.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home) / "config.toml"
    user_profile = env.get("USERPROFILE") or env.get("HOME")
    if user_profile:
        return Path(user_profile) / ".codex" / "config.toml"
    return Path("config.toml")


def _detect_mcp_registration(config_text: str) -> Dict[str, bool]:
    """检测 config.toml 是否注册了项目 MCP server（只返回布尔值）。"""

    result: Dict[str, bool] = {}
    for server_name in MCP_SERVER_NAMES:
        result[server_name.replace("-", "_") + "_registered"] = server_name in config_text
    return result


def _parse_bolt_endpoint(uri: str) -> Optional[tuple]:
    """解析 bolt://host:port（容忍 userinfo 与缺省端口）。"""

    match = re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://([^/?#]+)", uri)
    if not match:
        return None
    authority = match.group(1)
    if "@" in authority:
        authority = authority.rsplit("@", 1)[-1]
    if ":" in authority:
        host, _, port_text = authority.rpartition(":")
        if not host:
            return None
        try:
            port = int(port_text)
        except ValueError:
            return None
    else:
        host, port = authority, DEFAULT_BOLT_PORT
    return host, port


def _neo4j_port_listening(uri: str, connect_timeout: float) -> bool:
    """只做 TCP 连通性探测；不发送凭据、不执行任何查询。"""

    endpoint = _parse_bolt_endpoint(uri)
    if endpoint is None:
        return False
    host, port = endpoint
    try:
        with socket.create_connection((host, port), timeout=connect_timeout):
            return True
    except OSError:
        return False


def run_preflight(
    env: Mapping[str, str],
    config_path: Optional[Path],
    connect_timeout: float = 2.0,
    config_text_override: Optional[str] = None,
) -> Dict[str, Any]:
    """生成前置门报告；只读，不打印任何密钥真实值。"""

    config_text = ""
    config_exists = config_path is not None and config_path.is_file()
    if config_text_override is not None:
        config_text = config_text_override
        config_exists = True
    elif config_exists:
        try:
            config_text = Path(config_path).read_text(encoding="utf-8")
        except OSError:
            config_text = ""

    mcp_checks = _detect_mcp_registration(config_text)
    mcp_registered = any(mcp_checks.values())

    neo4j_env = {var: (var in env and bool(env[var])) for var in NEO4J_ENV_VARS}
    neo4j_env_complete = all(neo4j_env.values())
    uri = env.get("NEO4J_URI", "")
    port_listening = _neo4j_port_listening(uri, connect_timeout) if neo4j_env_complete else False

    provider = env.get(RECOGNITION_PROVIDER_VAR)
    dashscope_key_set = bool(env.get(DASHSCOPE_KEY_VAR))
    recognition_qwen_ready = provider == "qwen" and dashscope_key_set

    available_entries: List[str] = []
    if mcp_checks["drawing_graph_qa_registered"]:
        available_entries.append("mcp_qa")
    if mcp_checks["drawing_assistant_registered"]:
        available_entries.append("mcp_assistant")
    if neo4j_env_complete and port_listening:
        available_entries.append("cli_neo4j")
    if recognition_qwen_ready:
        available_entries.append("recognition_qwen")

    blocked_reasons: List[str] = []
    if not mcp_registered:
        blocked_reasons.append("mcp_not_registered")
    if not neo4j_env_complete:
        blocked_reasons.append("neo4j_env_missing")
    elif not port_listening:
        blocked_reasons.append("neo4j_port_closed")
    if provider != "qwen":
        blocked_reasons.append("recognition_provider_missing")
    elif not dashscope_key_set:
        blocked_reasons.append("dashscope_key_missing")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ok": bool(available_entries),
        "checks": {
            "mcp": {
                "config_file_exists": config_exists,
                **mcp_checks,
            },
            "neo4j": {
                **{var.lower() + "_set": value for var, value in neo4j_env.items()},
                "port_listening": port_listening,
            },
            "recognition": {
                "provider": provider,
                "dashscope_api_key_set": dashscope_key_set,
            },
            "project": {
                var.lower() + "_set": bool(env.get(var)) for var in PROJECT_ENV_VARS
            },
        },
        "available_entries": available_entries,
        "blocked": not available_entries,
        "blocked_reasons": blocked_reasons,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="drawing-graph-operator 只读前置门检查")
    parser.add_argument("--config-path", default=None, help="Codex config.toml 路径（默认按环境解析）")
    parser.add_argument("--connect-timeout", type=float, default=2.0, help="TCP 探测超时秒数")
    args = parser.parse_args(argv)

    config_path = Path(args.config_path) if args.config_path else _default_config_path(os.environ)
    report = run_preflight(os.environ, config_path, args.connect_timeout)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
