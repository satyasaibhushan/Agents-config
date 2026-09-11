import importlib.util
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('install_git', ROOT / 'scripts/install-git.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def git_get(home, key, env=None):
    # Effective value: --global reads a single file and ignores includes.
    result = subprocess.run(['git', 'config', '--get', key], cwd=home,
                            env={**os.environ, **(env or {}), 'HOME': str(home)},
                            capture_output=True, text=True)
    return result.stdout.rstrip('\n') if result.returncode == 0 else None


def make_git_root(path, name='Sai Bhushan'):
    path.mkdir(parents=True)
    (path / 'gitconfig').write_text('[user]\n\tname = ' + name + '\n')
    (path / 'ignore').write_text('.DS_Store\n')
    # gh ships `co` as a built-in alias, so use one it does not define.
    (path / 'gh.yaml').write_text('aliases:\n  prs: pr list --author @me\n')
    return path


def test_links_checkout_and_preserves_local_config(tmp_path):
    home = tmp_path / 'home'
    home.mkdir()
    (home / '.gitconfig').write_text(
        '[user]\n\tname = Sai Bhushan\n\temail = old@example.com\n'
        '[http]\n\tpostBuffer = 524288000\n[core]\n\texcludesFile = ~/.gitignore_global\n')
    git_root = make_git_root(tmp_path / 'checkout' / 'Git')
    env = {'GH_CONFIG_DIR': str(tmp_path / 'gh')}

    changes = module.install(home, git_root, {'git_email': 'new@example.com'}, env)

    assert git_get(home, 'include.path') == str(git_root / 'gitconfig')
    assert git_get(home, 'core.excludesFile') == str(git_root / 'ignore')
    assert git_get(home, 'user.email') == 'new@example.com'
    assert git_get(home, 'user.name') == 'Sai Bhushan'
    assert git_get(home, 'http.postBuffer') == '524288000'
    local = (home / '.gitconfig').read_text()
    assert 'name =' not in local  # now served by the shared include
    assert 'postBuffer' in local
    backups = list((home / '.local/state/agents-config/backups').glob('git-*'))
    assert len(backups) == 1
    assert 'old@example.com' in (backups[0] / '0-.gitconfig').read_text()
    assert changes

    # Second run: nothing to do, no new backup.
    assert module.install(home, git_root, {'git_email': 'new@example.com'}, env) == []
    assert len(list((home / '.local/state/agents-config/backups').glob('git-*'))) == 1


def test_pull_updates_shared_values_without_reinstall(tmp_path):
    home = tmp_path / 'home'
    home.mkdir()
    git_root = make_git_root(tmp_path / 'checkout' / 'Git')
    env = {'GH_CONFIG_DIR': str(tmp_path / 'gh')}
    module.install(home, git_root, None, env)
    (git_root / 'gitconfig').write_text('[user]\n\tname = Renamed\n[alias]\n\tst = status\n')
    assert git_get(home, 'user.name') == 'Renamed'
    assert git_get(home, 'alias.st') == 'status'
    assert git_get(home, 'user.email') is None


def test_replaces_stale_checkout_include(tmp_path):
    home = tmp_path / 'home'
    home.mkdir()
    (home / '.gitconfig').write_text('[include]\n\tpath = /old/Agents/Config/Git/gitconfig\n')
    git_root = make_git_root(tmp_path / 'checkout' / 'Git')
    module.install(home, git_root, None, {'GH_CONFIG_DIR': str(tmp_path / 'gh')})
    result = subprocess.run(['git', 'config', '--global', '--get-all', 'include.path'],
                            env={**os.environ, 'HOME': str(home)},
                            capture_output=True, text=True, check=True)
    assert result.stdout.splitlines() == [str(git_root / 'gitconfig')]


def test_differing_local_name_is_kept(tmp_path, capsys):
    home = tmp_path / 'home'
    home.mkdir()
    (home / '.gitconfig').write_text('[user]\n\tname = Someone Else\n')
    git_root = make_git_root(tmp_path / 'checkout' / 'Git')
    module.install(home, git_root, None, {'GH_CONFIG_DIR': str(tmp_path / 'gh')})
    assert 'name = Someone Else' in (home / '.gitconfig').read_text()
    assert 'warning: local user.name' in capsys.readouterr().out


def test_global_ignore_applies_in_repositories(tmp_path):
    home = tmp_path / 'home'
    home.mkdir()
    git_root = make_git_root(tmp_path / 'checkout' / 'Git')
    module.install(home, git_root, None, {'GH_CONFIG_DIR': str(tmp_path / 'gh')})
    repo = tmp_path / 'repo'
    repo.mkdir()
    env = {**os.environ, 'HOME': str(home)}
    subprocess.run(['git', 'init', '-q'], cwd=repo, env=env, check=True)
    (repo / '.DS_Store').write_text('')
    (repo / 'kept.txt').write_text('')
    result = subprocess.run(['git', 'status', '--porcelain', '--ignored'], cwd=repo, env=env,
                            capture_output=True, text=True, check=True)
    assert result.stdout.splitlines() == ['?? kept.txt', '!! .DS_Store']


def test_gh_aliases(tmp_path):
    if not shutil.which('gh'):
        pytest.skip('gh unavailable')
    home = tmp_path / 'home'
    home.mkdir()
    git_root = make_git_root(tmp_path / 'checkout' / 'Git')
    env = {'GH_CONFIG_DIR': str(tmp_path / 'gh')}
    changes = module.install(home, git_root, None, env)
    assert 'gh alias prs = pr list --author @me' in changes
    result = subprocess.run(['gh', 'alias', 'list'], env={**os.environ, **env},
                            capture_output=True, text=True, check=True)
    assert 'prs: pr list --author @me' in result.stdout
    assert module.install(home, git_root, None, env) == []


def test_selected_profile_reads_saved_choice(tmp_path):
    home = tmp_path / 'home'
    (home / '.config/agents-config').mkdir(parents=True)
    (home / '.config/agents-config/config.json').write_text('{"profile": "mac-admin"}')
    profile = module.selected_profile(home, None)
    assert profile['name'] == 'mac-admin'
    assert '@' in profile['git_email']
    assert module.selected_profile(tmp_path, None) is None
    with pytest.raises(ValueError):
        module.selected_profile(home, 'nope')


def test_canonical_files_are_valid():
    root = ROOT / 'Git'
    assert module.canonical_user_name(root / 'gitconfig') == 'Sai Bhushan'
    assert module.gh_aliases(root / 'gh.yaml') == {'co': 'pr checkout'}
    assert '.agents/scripts/' in (root / 'ignore').read_text()
