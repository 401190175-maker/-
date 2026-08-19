import importlib.util
import json
import os
import socket
import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "skill_preflight.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("skill_preflight", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clean_env(**overrides):
    base = {
        key: value
        for key, value in os.environ.items()
        if key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE")
    }
    for key in (
        "NEO4J_URI",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
        "DRAWING_GRAPH_DATA_ROOT",
        "DRAWING_GRAPH_PROJECT_SLUG",
        "DRAWING_GRAPH_RECOGNITION_PROVIDER",
        "DASHSCOPE_API_KEY",
        "CODEX_HOME",
    ):
        base.pop(key, None)
    base.update(overrides)
    return base


class SkillPreflightLogicTests(unittest.TestCase):
    """run_preflight 的只读逻辑测试（不连接真实 Neo4j）。"""

    def setUp(self):
        self.module = _load_module()

    def test_blocked_when_no_entries_available(self):
        report = self.module.run_preflight(_clean_env(), Path("missing-config.toml"), 0.5)
        self.assertFalse(report["ok"])
        self.assertTrue(report["blocked"])
        self.assertEqual([], report["available_entries"])
        self.assertIn("mcp_not_registered", report["blocked_reasons"])
        self.assertIn("neo4j_env_missing", report["blocked_reasons"])

    def test_cli_neo4j_available_when_env_complete_and_port_open(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(5)
        port = sock.getsockname()[1]
        try:
            env = _clean_env(
                NEO4J_URI=f"bolt://127.0.0.1:{port}",
                NEO4J_USER="neo4j",
                NEO4J_PASSWORD="pw",
            )
            report = self.module.run_preflight(env, Path("missing-config.toml"), 1.0)
        finally:
            sock.close()
        self.assertIn("cli_neo4j", report["available_entries"])
        self.assertFalse(report["blocked"])
        self.assertTrue(report["checks"]["neo4j"]["port_listening"])

    def test_uri_parsing_tolerates_userinfo_and_default_port(self):
        self.assertEqual(( "127.0.0.1", 7687), self.module._parse_bolt_endpoint("bolt://127.0.0.1"))
        self.assertEqual(("127.0.0.1", 9999), self.module._parse_bolt_endpoint("bolt://user:pw@127.0.0.1:9999"))
        self.assertIsNone(self.module._parse_bolt_endpoint("not-a-uri"))

    def test_mcp_registration_detection_is_a_pure_text_check(self):
        config_text = (
            '[mcp_servers.drawing-graph-qa]\ncommand="x"\n\n'
            '[mcp_servers.drawing-assistant]\ncommand="y"\n'
        )
        checks = self.module._detect_mcp_registration(config_text)
        self.assertTrue(checks["drawing_graph_qa_registered"])
        self.assertTrue(checks["drawing_assistant_registered"])
        missing = self.module.run_preflight(_clean_env(), Path("missing-config.toml"), 0.5)
        self.assertFalse(missing["checks"]["mcp"]["config_file_exists"])

    def test_mcp_registration_detection_can_drive_available_entries(self):
        config_text = '[mcp_servers.drawing-graph-qa]\ncommand="x"\n'
        report = self.module.run_preflight(
            _clean_env(),
            Path("missing-config.toml"),
            0.5,
            config_text_override=config_text,
        )
        self.assertTrue(report["checks"]["mcp"]["drawing_graph_qa_registered"])
        self.assertIn("mcp_qa", report["available_entries"])

    def test_report_never_contains_secret_values(self):
        secrets = ("sentinel-password-abc123", "sentinel-dashscope-key-xyz")
        env = _clean_env(
            NEO4J_URI="bolt://127.0.0.1:9",
            NEO4J_USER="neo4j",
            NEO4J_PASSWORD=secrets[0],
            DASHSCOPE_API_KEY=secrets[1],
            DRAWING_GRAPH_RECOGNITION_PROVIDER="qwen",
        )
        report = self.module.run_preflight(env, Path("missing-config.toml"), 0.5)
        text = json.dumps(report, ensure_ascii=False)
        for secret in secrets:
            self.assertNotIn(secret, text)


class SkillPreflightCliTests(unittest.TestCase):
    """脚本入口的端到端只读测试。"""

    def test_blocked_exit_code_and_valid_json_without_secrets(self):
        secrets = ("sentinel-password-abc123", "sentinel-dashscope-key-xyz")
        env = _clean_env(
            NEO4J_URI="bolt://127.0.0.1:9",
            NEO4J_USER="neo4j",
            NEO4J_PASSWORD=secrets[0],
            DASHSCOPE_API_KEY=secrets[1],
        )
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--config-path",
                str(PROJECT_ROOT / "missing_preflight_config.toml"),
                "--connect-timeout",
                "0.5",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(PROJECT_ROOT),
        )
        self.assertEqual(3, proc.returncode)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["blocked"])
        for secret in secrets:
            self.assertNotIn(secret, proc.stdout)
            self.assertNotIn(secret, proc.stderr)

    def test_script_source_contains_no_write_operations(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        for marker in (
            "write_text",
            "write_bytes",
            "os.remove",
            "os.rmdir",
            "unlink",
            "shutil.",
            "mkdir",
            "open(",
        ):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, source)


if __name__ == "__main__":
    unittest.main()
