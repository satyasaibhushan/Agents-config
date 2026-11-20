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
    claude = tmp_path / '.claude'
    claude.mkdir()
    (claude / 'settings.json').write_text(json.dumps({
        'permissions': {'deny': ['Read(//**/.env*)', 'Edit(//other/private)']},
    }))
    script = Path(__file__).resolve().parents[1] / 'scripts/development-access.py'
    for _ in range(2):
        subprocess.run([sys.executable, str(script)], env={**os.environ, 'HOME': str(tmp_path)}, check=True, capture_output=True)
    result = tomllib.loads(config.read_text())
    assert result['model'] == 'existing'
    assert result['mcp_servers']['existing']['command'] == 'existing'
    # A permissions profile replaces the legacy sandbox table; codex rejects mixing them.
    assert 'sandbox_workspace_write' not in result
    assert result['default_permissions'] == 'development'
    profile = result['permissions']['development']
    assert profile['extends'] == ':workspace'
    assert profile['filesystem'][str(tmp_path / 'Agents')] == 'write'
    assert not [k for k in profile['filesystem'] if k.startswith('/**')]
    assert profile['filesystem']['glob_scan_max_depth'] == 8
    assert profile['network']['enabled'] is True
    assert list(result['permissions']) == ['development']
    policy = json.loads((tmp_path / '.config/agents-config/development.json').read_text())
    assert str(tmp_path / 'Agents') in policy['directories']
    assert 'Bash' in policy['allow']
    settings = json.loads((tmp_path / '.claude/settings.json').read_text())
    permissions = settings['permissions']
    assert 'Read(//**/.env*)' not in permissions['deny']
    assert 'Edit(//other/private)' in permissions['deny']
    for command in ('env-keys', 'env-hosts', 'env-set'):
        assert f'Bash({command} *)' in permissions['allow']
    for glob in policy['deny_read_and_edit']:
        assert profile['filesystem'][str(tmp_path / 'Agents') + '/' + glob] == 'deny'
        assert permissions['deny'].count(f'Read(//{glob})') == 1
        assert permissions['deny'].count(f'Edit(//{glob})') == 1


def test_dotenv_globs_allow_only_example_templates(tmp_path):
    root = Path(__file__).resolve().parents[1]
    policy = json.loads((root / 'Permissions/development.json').read_text())
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    (tmp_path / '.gitignore').write_text('\n'.join(policy['deny_read_and_edit']) + '\n')
    denied = [
        '.env', '.env.local', 'nested/.env.uat', 'app.env', 'a/b/app.env.local',
        '.env.example.local', '.env.private.example', 'app.envenv.example',
        '.enve', '.envle', '.envple', '.envmple', '.envample', '.envxample', '.envexample',
    ]
    allowed = ['.env.example', 'a/b/.env.example', 'a/app.env.example',
               'app.env.service.env.example', 'package.json']
    result = subprocess.run(
        ['git', '-C', str(tmp_path), 'check-ignore', '--stdin', '--no-index'],
        input='\n'.join(denied + allowed) + '\n', text=True, capture_output=True, check=True,
    )
    assert result.stdout.splitlines() == denied
