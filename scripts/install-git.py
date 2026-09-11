#!/usr/bin/env python3
"""Wire the shared Git configuration into the account's global git config.

Canonical files live under Git/ in the checkout and are reached by reference,
so a pull updates every linked account:

  Git/gitconfig  -> include.path
  Git/ignore     -> core.excludesFile
  Git/gh.yaml    -> gh aliases (gh alias set --clobber; skipped without gh)

user.email is per profile (profiles.yaml git_email) and written as a literal
value into the global config. Local git config is otherwise left alone; the
global config file is backed up before the first write.
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


CHECKOUT = Path(__file__).resolve().parents[1]
GIT_ROOT = CHECKOUT / 'Git'


def load_yaml_subset():
    spec = importlib.util.spec_from_file_location('apply', CHECKOUT / 'scripts/apply.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_yaml_subset


def selected_profile(home, name):
    """Profile from --profile or the choice saved by `agents-config apply`.
    Returns None when nothing is selected; email is then left alone."""
    if not name:
        saved = home / '.config/agents-config/config.json'
        if not saved.exists():
            return None
        name = json.loads(saved.read_text()).get('profile')
    if not name:
        return None
    profiles = load_yaml_subset()((CHECKOUT / 'profiles.yaml').read_text(),
                                  origin='profiles.yaml').get('profiles') or {}
    if name not in profiles:
        raise ValueError('unknown profile ' + repr(name))
    return {'name': name, **profiles[name]}


class Git:
    def __init__(self, home, env):
        self.env = {**os.environ, **env, 'HOME': str(home)}

    def run(self, *args, check=True):
        result = subprocess.run(['git', 'config', '--global', *args], env=self.env,
                                capture_output=True, text=True)
        if check and result.returncode:
            raise RuntimeError(result.stderr.strip() or 'git config failed')
        return result

    def get(self, key):
        result = self.run('--get', key, check=False)
        return result.stdout.rstrip('\n') if result.returncode == 0 else None

    def get_all(self, key):
        result = self.run('--get-all', key, check=False)
        return result.stdout.splitlines() if result.returncode == 0 else []

    def config_file(self):
        result = self.run('--list', '--show-origin', check=False)
        for line in result.stdout.splitlines():
            origin = line.split('\t', 1)[0]
            if origin.startswith('file:'):
                return Path(origin[len('file:'):])
        return None


def canonical_user_name(gitconfig):
    result = subprocess.run(['git', 'config', '--file', str(gitconfig), '--get', 'user.name'],
                            capture_output=True, text=True)
    return result.stdout.rstrip('\n') if result.returncode == 0 else None


def gh_aliases(gh_yaml):
    data = load_yaml_subset()(gh_yaml.read_text(), origin='Git/gh.yaml')
    aliases = data.get('aliases') or {}
    if not isinstance(aliases, dict):
        raise ValueError('Git/gh.yaml: aliases must be a mapping')
    return aliases


def live_gh_aliases(env):
    result = subprocess.run(['gh', 'alias', 'list'], env=env, capture_output=True, text=True)
    live = {}
    for line in result.stdout.splitlines():
        name, sep, expansion = line.partition(':')
        if sep:
            live[name.strip()] = expansion.strip()
    return live


def backup_once(home, files, state):
    """Copy each existing file into one git-* backup dir, the first time only."""
    for path in files:
        if not path or not path.exists() or path in state['saved']:
            continue
        if state['dir'] is None:
            root = home / '.local/state/agents-config/backups'
            root.mkdir(parents=True, exist_ok=True)
            state['dir'] = Path(tempfile.mkdtemp(prefix='git-', dir=str(root)))
        shutil.copy2(path, state['dir'] / (str(len(state['saved'])) + '-' + path.name))
        state['saved'].add(path)


def install(home, git_root, profile, env=None):
    env = dict(env or {})
    git = Git(home, env)
    gitconfig = git_root / 'gitconfig'
    ignore = git_root / 'ignore'
    for path in (gitconfig, ignore):
        if not path.exists():
            raise FileNotFoundError(str(path))
    backups = {'dir': None, 'saved': set()}
    changes = []

    def set_value(key, value, value_regex=None):
        if value_regex is None:
            if git.get(key) == value:
                return
            backup_once(home, [git.config_file()], backups)
            git.run(key, value)
        else:
            if git.get_all(key) == [value]:
                return
            backup_once(home, [git.config_file()], backups)
            git.run('--replace-all', key, value, value_regex)
        changes.append(key + ' = ' + value)

    set_value('include.path', str(gitconfig), r'.*/Git/gitconfig$')
    set_value('core.excludesFile', str(ignore))

    # A local user.name would shadow the shared one when it follows the
    # include; drop it when it already matches, warn when it does not.
    shared_name = canonical_user_name(gitconfig)
    local_file = git.config_file()
    if shared_name and local_file:
        result = subprocess.run(['git', 'config', '--file', str(local_file), '--get', 'user.name'],
                                capture_output=True, text=True)
        local_name = result.stdout.rstrip('\n') if result.returncode == 0 else None
        if local_name == shared_name:
            backup_once(home, [local_file], backups)
            subprocess.run(['git', 'config', '--file', str(local_file), '--unset', 'user.name'],
                           check=True, capture_output=True)
            changes.append('user.name now comes from ' + str(gitconfig))
        elif local_name is not None:
            print('warning: local user.name ' + repr(local_name) + ' differs from shared '
                  + repr(shared_name) + '; left in place')

    email = (profile or {}).get('git_email')
    if email:
        set_value('user.email', email)
    else:
        print('note: no profile git_email; user.email left alone')

    gh_yaml = git_root / 'gh.yaml'
    if gh_yaml.exists() and shutil.which('gh'):
        gh_env = git.env
        gh_dir = Path(gh_env.get('GH_CONFIG_DIR') or (home / '.config/gh'))
        live = live_gh_aliases(gh_env)
        for name, expansion in gh_aliases(gh_yaml).items():
            if live.get(name) == expansion:
                continue
            backup_once(home, [gh_dir / 'config.yml'], backups)
            subprocess.run(['gh', 'alias', 'set', '--clobber', name, expansion], env=gh_env,
                           check=True, capture_output=True)
            changes.append('gh alias ' + name + ' = ' + expansion)
    elif gh_yaml.exists():
        print('note: gh not installed; aliases skipped')

    for change in changes:
        print('updated: ' + change)
    if backups['dir']:
        print('backup: ' + str(backups['dir']))
    if not changes:
        print('git configuration already in sync')
    return changes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--profile', help='profile name (default: saved by agents-config apply)')
    args = parser.parse_args(argv)
    home = Path.home()
    try:
        profile = selected_profile(home, args.profile)
        install(home, GIT_ROOT, profile)
    except (ValueError, RuntimeError, FileNotFoundError) as error:
        sys.exit('error: ' + str(error))


if __name__ == '__main__':
    main()
