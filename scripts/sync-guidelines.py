#!/usr/bin/env python3
"""Sync the personal guidelines fork; --install also configures DevSpace and cron."""

import argparse
from pathlib import Path
import shlex
import shutil
import subprocess
import sys


REPOSITORY = 'satyasaibhushan/guidelines'
FORK = 'git@github.com:' + REPOSITORY + '.git'
UPSTREAM = 'git@github.com:vmockinc/guidelines.git'
MARKER = '# guidelines fork sync'


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def prepare_cache(cache):
    # DevSpace uses go-git and ignores Git's insteadOf URL rewrites.
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        run('git', 'clone', '--branch', 'master', FORK, str(cache))
        return
    def git(*args):
        return run('git', '-C', str(cache), *args)
    if git('status', '--porcelain'):
        raise ValueError('DevSpace guidelines cache has local edits; left untouched')
    if git('branch', '--show-current') != 'master':
        raise ValueError('DevSpace guidelines cache is not on master; left untouched')
    if git('remote', 'get-url', 'origin') not in (UPSTREAM, FORK):
        raise ValueError('DevSpace guidelines cache has an unexpected origin; left untouched')
    git('fetch', FORK, 'master')
    try:
        git('merge', '--no-edit', 'FETCH_HEAD')
    except subprocess.CalledProcessError:
        # Only abort the merge started above, after proving the cache was clean.
        git('merge', '--abort')
        raise
    git('remote', 'set-url', 'origin', FORK)


def cron_content(old, command):
    lines = [line for line in old.splitlines() if not line.endswith(MARKER)]
    # Cron treats percent signs specially, even inside shell quotes.
    lines.append('30 7 * * * ' + command.replace('%', r'\%') + ' ' + MARKER)
    return '\n'.join(lines) + '\n'


def install(home):
    prepare_cache(home / '.devspace/dependencies/git-github-com-vmockinc-guidelines-git-master')
    current = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    if current.returncode and 'no crontab for' not in current.stderr.lower():
        raise RuntimeError(current.stderr.strip())
    gh = shutil.which('gh')
    # Keep the scheduled job working when this checkout switches branches.
    runner = home / '.local/lib/guidelines/sync.py'
    runner.parent.mkdir(parents=True, exist_ok=True)
    if Path(__file__).resolve() != runner.resolve():
        shutil.copyfile(Path(__file__).resolve(), runner)
    command = shlex.join([sys.executable, str(runner), '--gh', gh])
    content = cron_content(current.stdout, command)
    subprocess.run(['crontab', '-'], input=content, check=True, text=True)
    installed = run('crontab', '-l')
    if installed != content.strip():
        raise RuntimeError('Installed crontab differs from requested schedule')
    print('DevSpace uses the fork; sync scheduled daily at 07:30 local time')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--gh', default='gh', help='GitHub CLI path for scheduled runs')
    args = parser.parse_args()
    # GitHub merges upstream without force resetting our fork patches.
    print(run(args.gh, 'api', '-X', 'POST', 'repos/' + REPOSITORY + '/merge-upstream',
              '-f', 'branch=master'))
    if args.install:
        install(Path.home())


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(getattr(error, 'stderr', None) or str(error))
