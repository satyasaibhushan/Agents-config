import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path


def test_development_apply_preserves_other_settings(tmp_path):
    (tmp_path / '.config/agents-config').mkdir(parents=True)
    (tmp_path / '.config/agents-config/config.json').write_text('{"profile":"devbox-admin"}')
    (tmp_path / '.codex').mkdir()
    config = tmp_path / '.codex/config.toml'
    config.write_text('model = "existing"\n[sandbox_workspace_write]\nexclude_tmpdir_env_var = true\n[mcp_servers.existing]\ncommand = "existing"\n')
    script = Path(__file__).resolve().parents[1] / 'scripts/development-access.py'
    for _ in range(2):
        subprocess.run([sys.executable, str(script)], env={**os.environ, 'HOME': str(tmp_path)}, check=True, capture_output=True)
    result = tomllib.loads(config.read_text())
    assert result['model'] == 'existing'
    assert result['mcp_servers']['existing']['command'] == 'existing'
    assert result['sandbox_workspace_write']['exclude_tmpdir_env_var'] is True
    assert result['sandbox_workspace_write']['network_access'] is True
    policy = json.loads((tmp_path / '.config/agents-config/development.json').read_text())
    assert str(tmp_path / 'Agents') in policy['directories']
    assert 'Bash' in policy['allow']
