#!/usr/bin/env python3
"""Tests for scripts/apply.py. Stdlib only. Every test runs against a
temporary home directory so a test run can never touch real agent config.

Run:  python3 -m unittest discover -s tests
"""

import json
import importlib.util
import os
import subprocess
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
        self.write(".codex/config.toml", "\n".join([
            '[mcp_servers.node_repl]',
            'command = "node"',
            '[mcp_servers.computer-use]',
            'command = "computer-use"',
            '[mcp_servers.openaiDeveloperDocs]',
            'url = "https://developers.openai.com/mcp"',
        ]))
        items, _ = self.plan(servers={})
        for name in ("node_repl", "computer-use", "openaiDeveloperDocs"):
            self.assertNotIn(name, items)

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

        profile = {"name": "test", "skills": "default-allow"}
        items, canonical = self.apply.plan_skills(self.home, {}, profile)
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
        profile = {"name": "test", "skills": "default-allow"}
        targets = {"demo": {"clients": ["claude-code"]}}
        items, _ = self.apply.plan_skills(self.home, targets, profile)
        self.assertEqual(items["demo"]["codex"]["state"], A.UNTARGETED)
        self.assertEqual(items["demo"]["claude-code"]["state"], A.MISSING)

    def test_default_deny_only_installs_explicitly_allowed_skills(self):
        (self.canonical / "blocked").mkdir()
        (self.canonical / "blocked" / "SKILL.md").write_text("blocked\n")
        profile = {"name": "devbox-agent", "skills": "default-deny"}
        targets = {
            "demo": {"profiles": ["devbox-agent"]},
            "blocked": {},
        }
        items, _ = self.apply.plan_skills(self.home, targets, profile)
        self.assertIn("demo", items)
        self.assertNotIn("blocked", items)

    def test_skill_manifest_profiles_are_validated_and_preserved(self):
        manifest = self.tmp / "skills.json"
        manifest.write_text(json.dumps({"version": 1, "skills": {
            "demo": {"clients": ["codex"], "profiles": ["devbox-agent"]}
        }}))
        self.apply.SKILLS_MANIFEST = manifest
        targets = self.apply.load_skill_targets({"devbox-agent": {}})
        self.assertEqual(targets["demo"]["profiles"], ["devbox-agent"])
        self.apply.write_skill_targets(targets)
        saved = json.loads(manifest.read_text())["skills"]["demo"]
        self.assertEqual(saved["profiles"], ["devbox-agent"])

        manifest.write_text(json.dumps({"version": 1, "skills": {
            "demo": {"profiles": ["unknown"]}
        }}))
        with self.assertRaises(SystemExit):
            self.apply.load_skill_targets({"devbox-agent": {}})


BASE = "# Base\n\nShared rules.\n"
EXTRA = "# Claude extras\n\nModel table.\n"


class InstructionsPlanTest(ApplyTestCase):
    PROFILE = {"name": "test", "fragments": ["base.md"]}

    def setUp(self):
        super().setUp()
        self.instr = self.tmp / "Instructions"
        (self.instr / "fragments").mkdir(parents=True)
        (self.instr / "providers").mkdir()
        (self.instr / "fragments" / "base.md").write_text(BASE)
        (self.instr / "providers" / "claude-code.md").write_text(EXTRA)
        self.apply.INSTRUCTIONS_ROOT = self.instr

    def targets(self):
        return {
            "claude-code": {"path": "~/.claude/CLAUDE.md", "legacy": "~/CLAUDE.md",
                            "extra": "providers/claude-code.md"},
            "codex": {"path": "~/.codex/AGENTS.md"},
        }

    def plan(self, targets=None):
        return self.apply.plan_instructions(
            targets or self.targets(), self.home, self.PROFILE, None)

    def rendered(self, *relpaths):
        return self.apply.render_instruction(list(relpaths))[0]

    def test_render_is_fragment_concatenation(self):
        self.assertEqual(self.rendered("fragments/base.md"), BASE)
        self.assertEqual(
            self.rendered("fragments/base.md", "providers/claude-code.md"),
            BASE.rstrip("\n") + "\n\n" + EXTRA)

    def test_states(self):
        A = self.apply
        self.write(".codex/AGENTS.md", self.rendered("fragments/base.md"))
        items = self.plan()
        self.assertEqual(items["codex"]["state"], A.IN_SYNC)
        self.assertEqual(items["claude-code"]["state"], A.MISSING)

        self.write(".claude/CLAUDE.md", "# Base\nedited\n")
        items = self.plan()
        self.assertEqual(items["claude-code"]["state"], A.MODIFIED)

    def test_legacy_path_migration(self):
        A = self.apply
        desired = self.rendered("fragments/base.md", "providers/claude-code.md")
        # only the legacy file exists, content already right -> migrate
        self.write("CLAUDE.md", desired)
        items = self.plan()
        cell = items["claude-code"]
        self.assertEqual(cell["state"], A.MIGRATE)
        self.assertEqual(cell["legacy"], self.home / "CLAUDE.md")

        writes, removals = self.apply.final_instructions(
            items, self.targets(), {}, {"claude-code": "sync"},
            self.home, self.PROFILE, None)
        self.assertIn(("claude-code", self.home / ".claude/CLAUDE.md", desired),
                      writes)
        self.assertEqual(removals, [("claude-code", self.home / "CLAUDE.md")])

    def test_v1_manifest_still_renders_whole_source(self):
        A = self.apply
        (self.instr / "AGENTS.md").write_text("# V1\n")
        targets = {"codex": {"path": "~/.codex/AGENTS.md", "source": "AGENTS.md"}}
        items = self.apply.plan_instructions(targets, self.home, self.PROFILE,
                                             "AGENTS.md")
        self.assertEqual(items["codex"]["state"], A.MISSING)
        self.assertEqual(items["codex"]["desired"], "# V1\n")

    def test_provider_write_detaches_symlink_to_another_provider(self):
        codex = self.write(".codex/AGENTS.md", BASE)
        claude = self.home / ".claude/CLAUDE.md"
        claude.parent.mkdir(parents=True)
        claude.symlink_to(codex)
        desired_claude = BASE.rstrip("\n") + "\n\n" + EXTRA

        self.apply.write_instruction_files([
            ("claude-code", claude, desired_claude),
            ("codex", codex, BASE),
        ], self.home, "20260718-000003")

        self.assertFalse(claude.is_symlink())
        self.assertEqual(claude.read_text(), desired_claude)
        self.assertEqual(codex.read_text(), BASE)

    def test_promote_maps_hunks_to_fragments(self):
        desired, spans = self.apply.render_instruction(
            ["fragments/base.md", "providers/claude-code.md"])
        live = desired.replace("Shared rules.", "Sharper shared rules.") \
                      .replace("Model table.", "Better model table.")
        edits, boundary, blocked = self.apply.map_hunks_to_sources(
            desired.splitlines(), live.splitlines(), spans)
        self.assertFalse(boundary)
        self.assertFalse(blocked)
        self.assertEqual(sorted(edits),
                         ["fragments/base.md", "providers/claude-code.md"])

        overrides = {}
        for relpath, source_edits in edits.items():
            self.apply.apply_source_edits(relpath, source_edits, overrides)
        self.assertIn("Sharper shared rules.", overrides["fragments/base.md"])
        self.assertIn("Better model table.", overrides["providers/claude-code.md"])
        # promote ripple: re-render equals the live edit
        rerendered, _ = self.apply.render_instruction(
            ["fragments/base.md", "providers/claude-code.md"], overrides)
        self.assertEqual(rerendered, live)

    def test_boundary_spanning_edit_blocks_promote(self):
        desired, spans = self.apply.render_instruction(
            ["fragments/base.md", "providers/claude-code.md"])
        live = desired.replace("Shared rules.\n\n# Claude extras", "Merged section")
        _, _, blocked = self.apply.map_hunks_to_sources(
            desired.splitlines(), live.splitlines(), spans)
        self.assertTrue(blocked)


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


PROFILES = {
    "mac-admin": {"platform": "darwin", "mode": "read-write",
                  "fragments": ["base.md"]},
    "devbox-agent": {"platform": "linux", "mode": "read-only",
                     "mcps": "default-deny", "skills": "default-deny",
                     "fragments": ["base.md", "restricted-agent.md"],
                     "preflight": ["not-root"]},
}


class ProfileTest(ApplyTestCase):
    def args(self, *argv):
        return self.apply.parse_args(
            ["plan", "--home", str(self.home), *argv])

    def test_yaml_inline_lists(self):
        data = self.apply.load_yaml_subset(
            "profiles:\n"
            "  mac-admin:\n"
            "    fragments: [base.md, devbox.md]\n"
            "    preflight: []\n")
        entry = data["profiles"]["mac-admin"]
        self.assertEqual(entry["fragments"], ["base.md", "devbox.md"])
        self.assertEqual(entry["preflight"], [])

    def test_explicit_profile_resolves_and_validates_platform(self):
        args = self.args("--profile", "mac-admin", "--platform", "darwin")
        profile = self.apply.resolve_profile(args, PROFILES)
        self.assertEqual(profile["name"], "mac-admin")

        args = self.args("--profile", "mac-admin", "--platform", "linux")
        with self.assertRaises(SystemExit):
            self.apply.resolve_profile(args, PROFILES)

    def test_first_run_requires_profile(self):
        with self.assertRaises(SystemExit):
            self.apply.resolve_profile(self.args("--platform", "darwin"), PROFILES)
        with self.assertRaises(SystemExit):
            self.apply.resolve_profile(
                self.args("--profile", "nope", "--platform", "darwin"), PROFILES)

    def test_saved_profile_is_used_when_omitted(self):
        self.apply.save_local_config(self.home, {"profile": "mac-admin"})
        args = self.args("--platform", "darwin")
        profile = self.apply.resolve_profile(args, PROFILES)
        self.assertEqual(profile["name"], "mac-admin")
        config = self.home / ".config/agents-config/config.json"
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        self.assertEqual(config.parent.stat().st_mode & 0o777, 0o700)

    def test_repo_profiles_manifest_parses(self):
        profiles = self.apply.load_profiles()
        for name in ("mac-admin", "devbox-admin", "devbox-agent"):
            self.assertIn(name, profiles)
        agent = profiles["devbox-agent"]
        self.assertEqual(agent["mode"], "read-only")
        self.assertEqual(agent["mcps"], "default-deny")
        self.assertIn("restricted-agent.md", agent["fragments"])

    def test_unknown_preflight_check_fails(self):
        with self.assertRaises(SystemExit):
            self.apply.run_preflight({"preflight": ["frobnicate"]})
        self.apply.run_preflight({"preflight": ["not-root"]})  # passes as non-root

    def test_read_only_menu_drops_canonical_verbs(self):
        choices = {"p": "promote", "k": "keep", "o": "overwrite", "s": "skip"}
        self.assertEqual(
            list(self.apply.filter_choices(choices, read_only=True)), ["o", "s"])
        self.assertEqual(self.apply.filter_choices(choices, read_only=False), choices)

    def test_unwritable_checkout_forces_read_only(self):
        self.apply.CONFIG_ROOT = self.tmp / "checkout"
        self.apply.CONFIG_ROOT.mkdir()
        self.assertEqual(self.apply.effective_mode({"mode": "read-write"}), "read-write")
        self.apply.CONFIG_ROOT.chmod(0o500)
        try:
            self.assertEqual(self.apply.effective_mode({"mode": "read-write"}),
                             "read-only")
        finally:
            self.apply.CONFIG_ROOT.chmod(0o700)
        self.assertEqual(self.apply.effective_mode({"mode": "read-only"}), "read-only")


class McpScopeTest(ApplyTestCase):
    ADMIN = {"name": "mac-admin", "mcps": "default-allow", "code_root": "~/Code"}
    AGENT = {"name": "devbox-agent", "mcps": "default-deny",
             "code_root": "/srv/code"}

    def partition(self, servers, profile, platform="darwin", env=None):
        return self.apply.partition_servers(
            self.genmod, servers, profile, platform, env or {})

    def test_validation_rejects_unknown_keys_and_hardcoded_paths(self):
        for entry in (
            {"clients": ["codex"], "confg": {}},                    # typo key
            {"clients": ["emacs"]},                                  # bad client
            {"clients": ["codex"], "platforms": ["windows"]},        # bad platform
            {"clients": ["codex"], "profiles": ["nope"]},            # bad profile
            {"clients": ["codex"], "requires": {"binaries": []}},    # bad requires
            {"clients": ["codex"],
             "config": {"command": "/Users/me/bin/tool"}},           # hardcoded
            {"clients": ["codex"],
             "codex": {"args": ["/opt/homebrew/bin/x"]}},            # in override
        ):
            with self.assertRaises(SystemExit):
                self.apply.validate_servers({"bad": entry}, {"mac-admin": {}})
        self.apply.validate_servers({"ok": {
            "clients": ["codex"], "platforms": ["darwin"],
            "profiles": ["mac-admin"], "security": "reads-code",
            "requires": {"executables": ["python3"]},
            "config": {"command": "${HOME}/bin/tool",
                       "args": ["${CODE_ROOT}/repo"]},
        }}, {"mac-admin": {}})

    def test_platform_and_profile_filtering(self):
        servers = {
            "everywhere": {"clients": ["codex"], "config": {"command": "x"}},
            "mac-only": {"clients": ["codex"], "platforms": ["darwin"],
                         "config": {"command": "x"}},
            "agent-ok": {"clients": ["codex"], "profiles": ["devbox-agent"],
                         "config": {"command": "x"}},
        }
        in_scope, out = self.partition(servers, self.ADMIN, "darwin")
        self.assertEqual(sorted(in_scope), ["everywhere", "mac-only"])
        self.assertIn("not enabled for profile mac-admin", out["agent-ok"])

        in_scope, out = self.partition(servers, self.AGENT, "linux")
        self.assertEqual(sorted(in_scope), ["agent-ok"])   # explicit allow-list
        self.assertIn("denies MCPs by default", out["everywhere"])
        self.assertIn("darwin", out["mac-only"])

    def test_requires_filtering(self):
        servers = {"needs": {"clients": ["codex"], "config": {"command": "x"},
                             "requires": {"executables": ["no-such-binary-xyz"]}}}
        _, out = self.partition(servers, self.ADMIN)
        self.assertIn("executable 'no-such-binary-xyz'", out["needs"])

    def test_path_vars_expand_and_reverse_substitute(self):
        env = self.apply.path_vars({}, self.home, self.ADMIN)
        self.assertEqual(env["HOME"], str(self.home))
        self.assertEqual(env["CODE_ROOT"], str(self.home / "Code"))

        entry = {"clients": ["codex"],
                 "config": {"command": "${HOME}/bin/tool",
                            "args": ["${CODE_ROOT}/repo"]}}
        desired = self.apply.desired_mcp(self.genmod, "t", entry, "codex", env)
        self.assertEqual(desired["command"], f"{self.home}/bin/tool")
        self.assertEqual(desired["args"], [f"{self.home}/Code/repo"])

        # promote path: literal paths reverse to portable placeholders,
        # ${CODE_ROOT} winning over its ${HOME} prefix
        secret_map = self.apply.build_secret_map(env)
        masked = self.apply.reverse_substitute(desired, secret_map)
        self.assertEqual(masked["command"], "${HOME}/bin/tool")
        self.assertEqual(masked["args"], ["${CODE_ROOT}/repo"])

    def test_plan_ignores_out_of_scope_live_entries(self):
        self.write_json(".claude.json", {"mcpServers": {
            "mac-only": {"command": "x"},
        }})
        items, _ = self.apply.plan_mcps(self.genmod, {}, {}, self.home,
                                        ignore={"mac-only"})
        self.assertNotIn("mac-only", items)


class StateDirTest(ApplyTestCase):
    def test_backup_lands_in_home_state_dir(self):
        target = self.write(".claude/CLAUDE.md", "live\n")
        self.apply.backup(target, self.home, "20260718-000000")
        dest = (self.home / ".local/state/agents-config/backups/20260718-000000"
                / str(target).lstrip("/"))
        self.assertEqual(dest.read_text(), "live\n")
        self.assertEqual(dest.stat().st_mode & 0o777, 0o600)
        backups = self.home / ".local/state/agents-config/backups"
        self.assertEqual(backups.stat().st_mode & 0o777, 0o700)

    def test_backing_up_a_symlink_does_not_chmod_its_target(self):
        canonical = self.tmp / "canonical"
        canonical.write_text("skill\n")
        canonical.chmod(0o644)
        link = self.home / ".codex/skills/demo"
        link.parent.mkdir(parents=True)
        link.symlink_to(canonical)
        self.apply.backup(link, self.home, "20260718-000002")
        self.assertEqual(canonical.stat().st_mode & 0o777, 0o644)

    def test_new_mcp_configs_are_private(self):
        final = {client: {} for client in self.apply.MCP_CLIENTS}
        live = {client: {} for client in self.apply.MCP_CLIENTS}
        final["codex"] = {"demo": {"command": "demo"}}
        changed = self.apply.write_mcp_configs(
            final, live, self.home, self.genmod, "20260718-000001")
        path = self.home / ".codex/config.toml"
        self.assertEqual(changed, ["codex"])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)


class GeneratorSecurityTest(ApplyTestCase):
    def test_load_env_never_changes_permissions(self):
        env_path = self.write(".config/agents-config/mcp.env", "TOKEN=value\n")
        env_path.chmod(0o644)
        self.genmod.ENV_PATH = env_path
        self.genmod.LEGACY_ENV_PATH = self.tmp / "missing"
        self.genmod.load_env()
        self.assertEqual(env_path.stat().st_mode & 0o777, 0o644)
        with self.assertRaises(SystemExit):
            self.genmod.load_env(strict_permissions=True)
        self.assertEqual(env_path.stat().st_mode & 0o777, 0o644)

    def test_generated_output_defaults_to_user_state(self):
        output = self.genmod.generated_dir(self.home)
        self.assertEqual(
            output,
            self.home / ".local/state/agents-config/generated",
        )
        self.assertFalse(str(output).startswith(str(self.genmod.ROOT)))


class CliTest(ApplyTestCase):
    def test_plan_subcommand_and_flag(self):
        self.assertTrue(self.apply.parse_args(["plan"]).plan)
        self.assertTrue(self.apply.parse_args(["--plan"]).plan)
        self.assertFalse(self.apply.parse_args([]).plan)
        self.assertFalse(self.apply.parse_args(["apply"]).plan)

    def test_instruction_only_plan_does_not_touch_mcp_env(self):
        env_path = self.write(".config/agents-config/mcp.env", "TOKEN=value\n")
        env_path.chmod(0o644)
        before = env_path.stat().st_mode & 0o777
        env = dict(os.environ, HOME=str(self.home))
        subprocess.run([
            str(REPO / "scripts" / "agents-config"),
            "plan", "--only", "instructions", "--profile", "mac-admin",
            "--home", str(self.home), "--platform", "darwin",
        ], cwd=REPO, env=env, check=True, capture_output=True, text=True)
        self.assertEqual(env_path.stat().st_mode & 0o777, before)

    def test_installed_launcher_symlink_resolves_apply_script(self):
        launcher = self.tmp / "bin" / "agents-config"
        launcher.parent.mkdir()
        launcher.symlink_to(REPO / "scripts" / "agents-config")
        result = subprocess.run(
            [str(launcher), "--help"], cwd=REPO,
            check=True, capture_output=True, text=True)
        self.assertIn("Reconciling apply", result.stdout)


if __name__ == "__main__":
    unittest.main()
