#!/usr/bin/env python3
"""Tests for scripts/apply.py. Stdlib only. Every test runs against a
temporary home directory so a test run can never touch real agent config.

Run:  python3 -m unittest discover -s tests
"""

import json
import importlib.util
import tempfile
import tomllib
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ApplyTestCase(unittest.TestCase):
    """Fresh module + temp home per test: tests may monkeypatch module globals."""

    def setUp(self):
        self.apply = load_module("apply_under_test", REPO / "scripts" / "apply.py")
        self.genmod = self.apply.load_genmod()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp))
        self.home = self.tmp / "home"
        self.home.mkdir()

    def write(self, relpath, text):
        path = self.home / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def write_json(self, relpath, data):
        return self.write(relpath, json.dumps(data, indent=2) + "\n")


SERVERS = {
    "alpha": {
        "clients": ["claude-code", "codex"],
        "config": {"type": "stdio", "command": "alpha-mcp", "args": ["--x"]},
    },
    "beta": {
        "clients": ["cursor", "claude-code"],
        "config": {"url": "https://example.com/mcp",
                   "headers": {"api-key": "${DEMO_KEY}"}},
    },
}
ENV = {"DEMO_KEY": "secret-value-123"}


class McpPlanTest(ApplyTestCase):
    def plan(self, servers=SERVERS, env=ENV):
        return self.apply.plan_mcps(self.genmod, servers, env, self.home)

    def desired(self, name, client, servers=SERVERS, env=ENV):
        return self.apply.desired_mcp(self.genmod, name, servers[name], client, env)

    def test_states(self):
        self.write_json(".claude.json", {"mcpServers": {
            "alpha": self.desired("alpha", "claude-code"),   # in sync
            "stray": {"command": "stray-mcp"},               # not in canonical
        }})                                                  # beta -> missing
        self.write(".codex/config.toml",
                   '[mcp_servers.alpha]\ncommand = "alpha-mcp"\nargs = ["--y"]\n')
        self.write_json(".cursor/mcp.json", {"mcpServers": {
            "beta": self.desired("beta", "cursor"),          # in sync
            "alpha": {"command": "alpha-mcp"},               # cursor not targeted
        }})

        items, live_all = self.plan()
        A = self.apply
        self.assertEqual(items["alpha"]["claude-code"]["state"], A.IN_SYNC)
        self.assertEqual(items["beta"]["claude-code"]["state"], A.MISSING)
        self.assertEqual(items["stray"]["claude-code"]["state"], A.ADDED)
        self.assertEqual(items["alpha"]["codex"]["state"], A.MODIFIED)
        self.assertEqual(items["beta"]["cursor"]["state"], A.IN_SYNC)
        self.assertEqual(items["alpha"]["cursor"]["state"], A.UNTARGETED)

    def test_app_managed_servers_are_ignored(self):
        self.write(".codex/config.toml",
                   '[mcp_servers.node_repl]\ncommand = "node"\n')
        items, _ = self.plan(servers={})
        self.assertNotIn("node_repl", items)

    def test_secret_substitution_and_masking(self):
        desired = self.desired("beta", "claude-code")
        self.assertEqual(desired["headers"]["api-key"], ENV["DEMO_KEY"])
        secret_map = self.apply.build_secret_map(ENV)
        masked = self.apply.reverse_substitute(desired, secret_map)
        self.assertEqual(masked["headers"]["api-key"], "${DEMO_KEY}")

    def test_codex_toml_roundtrip(self):
        final = {"alpha": {"command": "alpha-mcp", "args": ["--x"],
                           "env": {"K": "v"}}}
        text = self.apply.codex_toml_section(final, self.genmod)
        parsed = tomllib.loads(text)["mcp_servers"]["alpha"]
        self.assertEqual(parsed, final["alpha"])


class SkillPlanTest(ApplyTestCase):
    def setUp(self):
        super().setUp()
        self.canonical = self.tmp / "canonical-skills"
        (self.canonical / "demo").mkdir(parents=True)
        (self.canonical / "demo" / "SKILL.md").write_text("demo\n")
        self.apply.CANONICAL_SKILLS = self.canonical

    def test_states(self):
        A = self.apply
        link = self.home / ".claude/skills/demo"
        link.parent.mkdir(parents=True)
        link.symlink_to(self.canonical / "demo")            # in sync

        copy = self.home / ".codex/skills/demo"             # unlinked, identical
        copy.mkdir(parents=True)
        (copy / "SKILL.md").write_text("demo\n")

        foreign = self.home / ".cursor/skills/demo"         # foreign symlink
        foreign.parent.mkdir(parents=True)
        foreign.symlink_to(self.tmp)

        extra = self.home / ".claude/skills/extra"          # live-only skill
        extra.mkdir()
        (extra / "SKILL.md").write_text("extra\n")

        items, canonical = self.apply.plan_skills(self.home, {})
        self.assertIn("demo", canonical)
        demo = items["demo"]
        self.assertEqual(demo["claude-code"]["state"], A.IN_SYNC)
        self.assertEqual(demo["codex"]["state"], A.UNLINKED)
        self.assertTrue(demo["codex"]["identical"])
        self.assertEqual(demo["cursor"]["state"], A.FOREIGN)
        self.assertEqual(demo["agents"]["state"], A.MISSING)
        self.assertEqual(items["extra"]["claude-code"]["state"], A.ADDED)

    def test_untargeted_skill(self):
        A = self.apply
        link = self.home / ".codex/skills/demo"
        link.parent.mkdir(parents=True)
        link.symlink_to(self.canonical / "demo")
        items, _ = self.apply.plan_skills(self.home, {"demo": ["claude-code"]})
        self.assertEqual(items["demo"]["codex"]["state"], A.UNTARGETED)
        self.assertEqual(items["demo"]["claude-code"]["state"], A.MISSING)


class InstructionsPlanTest(ApplyTestCase):
    def setUp(self):
        super().setUp()
        self.instr = self.tmp / "Instructions"
        self.instr.mkdir()
        (self.instr / "AGENTS.md").write_text("# Base\n")
        self.apply.INSTRUCTIONS_ROOT = self.instr

    def targets(self):
        return {
            "codex": {"path": "~/.codex/AGENTS.md", "source": "AGENTS.md"},
            "cursor": {"path": "~/AGENTS.md", "source": "AGENTS.md"},
        }

    def test_states(self):
        A = self.apply
        self.write(".codex/AGENTS.md", "# Base\n")          # in sync
        items = self.apply.plan_instructions(self.targets(), self.home)
        self.assertEqual(items["codex"]["state"], A.IN_SYNC)
        self.assertEqual(items["cursor"]["state"], A.MISSING)

        self.write("AGENTS.md", "# Base\nedited\n")
        items = self.apply.plan_instructions(self.targets(), self.home)
        self.assertEqual(items["cursor"]["state"], A.MODIFIED)


class YamlSubsetTest(ApplyTestCase):
    def test_nested_mappings(self):
        data = self.apply.load_yaml_subset(
            "version: 1\n"
            "default_source: AGENTS.md\n"
            "targets:\n"
            "  claude-code:\n"
            "    path: ~/CLAUDE.md   # comment\n"
            "    source: claude-code.md\n"
            "  codex:\n"
            "    path: ~/.codex/AGENTS.md\n"
        )
        self.assertEqual(data["version"], "1")
        self.assertEqual(data["targets"]["claude-code"]["source"], "claude-code.md")
        self.assertEqual(data["targets"]["codex"]["path"], "~/.codex/AGENTS.md")


class CliTest(ApplyTestCase):
    def test_plan_subcommand_and_flag(self):
        self.assertTrue(self.apply.parse_args(["plan"]).plan)
        self.assertTrue(self.apply.parse_args(["--plan"]).plan)
        self.assertFalse(self.apply.parse_args([]).plan)
        self.assertFalse(self.apply.parse_args(["apply"]).plan)


if __name__ == "__main__":
    unittest.main()
