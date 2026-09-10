import importlib.util
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('install_shell', ROOT / 'scripts/install-shell.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_preserves_local_files_and_is_idempotent(tmp_path):
    rc = tmp_path / '.bashrc'
    rc.write_text('alias local_only=true')
    profile = tmp_path / '.profile'
    profile.write_text('export LOCAL_SETTING=kept\n')
    source = tmp_path / "checkout with 'quotes'" / 'shared.sh'
    source.parent.mkdir()
    source.write_text('export SHARED_TEST=loaded\n')
    zsh_dir = tmp_path / 'zsh'
    module.install(tmp_path, source, zsh_dir)
    first = rc.read_text()
    module.install(tmp_path, source, zsh_dir)
    assert rc.read_text() == first
    assert first.startswith('alias local_only=true\n')
    assert profile.read_text().startswith('export LOCAL_SETTING=kept\n')
    assert not (tmp_path / '.bash_profile').exists()
    assert (zsh_dir / '.zshrc').exists()
    backups = list((tmp_path / '.local/state/agents-config/backups').glob('shell-*'))
    assert len(backups) == 1
    assert (backups[0] / '0-.bashrc').read_text() == 'alias local_only=true'


@pytest.mark.parametrize('shell', ['bash', 'zsh'])
def test_interactive_loading_and_pull_updates(tmp_path, shell):
    if not shutil.which(shell):
        pytest.skip(shell + ' unavailable')
    source = tmp_path / "checkout with 'quotes'" / 'shared.sh'
    source.parent.mkdir()
    source.write_text('export SHARED_TEST=first\n')
    module.install(tmp_path, source, tmp_path)
    env = {**os.environ, 'HOME': str(tmp_path), 'ZDOTDIR': str(tmp_path)}
    for value in ('first', 'updated'):
        source.write_text('export SHARED_TEST=' + value + '\n')
        for flags in ('-ic', '-lic'):
            result = subprocess.run([shell, flags, 'printf "%s" "$SHARED_TEST"'],
                                    env=env, capture_output=True, text=True, check=True)
            assert result.stdout == value
    result = subprocess.run([shell, '-c', 'printf "%s" "${SHARED_TEST-unset}"'],
                            env=env, capture_output=True, text=True, check=True)
    assert result.stdout == 'unset'


def test_bash_login_does_not_load_twice(tmp_path):
    (tmp_path / '.bash_profile').write_text('. "$HOME/.bashrc"\n')
    source = tmp_path / 'shared.sh'
    source.write_text('export LOAD_COUNT=$((${LOAD_COUNT:-0} + 1))\n')
    module.install(tmp_path, source, tmp_path)
    result = subprocess.run(['bash', '-lic', 'printf "%s" "$LOAD_COUNT"'],
                            env={**os.environ, 'HOME': str(tmp_path)},
                            capture_output=True, text=True, check=True)
    assert result.stdout == '1'


def test_invalid_markers_fail_before_writes(tmp_path):
    (tmp_path / '.zshrc').write_text(module.START + '\n')
    with pytest.raises(ValueError):
        module.install(tmp_path, ROOT / 'Shell/shared.sh', tmp_path)
    assert not (tmp_path / '.bashrc').exists()


@pytest.mark.parametrize('shell', ['bash', 'zsh'])
def test_shared_helpers_with_linux_paths(tmp_path, shell):
    if not shutil.which(shell):
        pytest.skip(shell + ' unavailable')
    code = tmp_path / 'code with spaces'
    target = code / 'backend/dashboard-api-accounts'
    target.mkdir(parents=True)
    script = '''
. "$SHARED_FILE"
eval accounts
pwd
uname() { printf 'Linux\\n'; }
unset DISPLAY WAYLAND_DISPLAY
open-repo-url https://example.com/compare
kubectl() { printf '%s\\n' "$*"; }
kx sample
kn sample
'''
    result = subprocess.run([shell, '-ic', script], env={
        **os.environ, 'HOME': str(tmp_path), 'ZDOTDIR': str(tmp_path),
        'CODE_ROOT': str(code), 'SHARED_FILE': str(ROOT / 'Shell/shared.sh'),
    }, capture_output=True, text=True, check=True)
    assert result.stdout.splitlines() == [str(target), 'https://example.com/compare',
                                         'config use-context sample',
                                         'config set-context --current --namespace sample']
