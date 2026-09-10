#!/usr/bin/env python3
"""Link shared shell configuration without replacing local startup files."""

import os
from pathlib import Path
import shlex
import shutil
import tempfile


START = '# >>> shared shell config >>>'
END = '# <<< shared shell config <<<'


def install(home, source, zsh_dir):
    login = next((home / name for name in ('.bash_profile', '.bash_login', '.profile')
                  if (home / name).exists()), home / '.bash_profile')
    changes = []
    for path in (home / '.bashrc', login, zsh_dir / '.zshrc'):
        old = path.read_text() if path.exists() else ''
        if old.count(START) != old.count(END) or old.count(START) > 1:
            raise ValueError('Invalid shared shell markers in ' + str(path))
        quoted = shlex.quote(str(source))
        # Bash login startup may already have sourced .bashrc.
        condition = '[ "${_SHARED_SHELL_SOURCE-}" != ' + quoted + ' ] && ' if path == login else ''
        block = '\n'.join([
            START,
            'case $- in',
            '    *i*)',
            '        if ' + condition + '[ -r ' + quoted + ' ]; then',
            '            . ' + quoted,
            '            _SHARED_SHELL_SOURCE=' + quoted,
            '        fi',
            '        ;;',
            'esac',
            END,
        ])
        if START in old:
            start = old.index(START)
            end = old.index(END)
            if end < start:
                raise ValueError('Invalid shared shell markers in ' + str(path))
            new = old[:start] + block + old[end + len(END):]
        else:
            new = old + ('\n' if old and not old.endswith('\n') else '') + '\n' + block + '\n'
        if old != new:
            changes.append((path, new))

    backup = None
    if any(path.exists() for path, _ in changes):
        root = home / '.local/state/agents-config/backups'
        root.mkdir(parents=True, exist_ok=True)
        backup = Path(tempfile.mkdtemp(prefix='shell-', dir=str(root)))
    for index, (path, new) in enumerate(changes):
        if path.exists():
            shutil.copy2(path, backup / (str(index) + '-' + path.name))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new)
        print('updated: ' + str(path))
    if backup:
        print('backup: ' + str(backup))


if __name__ == '__main__':
    home = Path.home()
    source = Path(__file__).resolve().parents[1] / 'Shell/shared.sh'
    install(home, source, Path(os.environ.get('ZDOTDIR') or home))
