#!/usr/bin/env python3
"""Store a user-entered HindSight ingestion token without displaying it."""

import getpass
import os
from pathlib import Path
import stat
import sys
import warnings


def owned_directory(path, create=False):
    if create:
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError("Storage directory must be a real directory owned by you.")


def main():
    if not sys.stdin.isatty():
        raise ValueError("Run this command directly in an interactive terminal.")
    os.umask(0o077)
    config = Path.home() / ".config"
    owned_directory(config, create=True)
    directory = config / "hindsight"
    owned_directory(directory, create=True)
    directory.chmod(0o700)
    target = directory / "mac-agents.token"
    if os.path.lexists(target):
        raise ValueError("A token file already exists; refusing to overwrite it.")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        token = getpass.getpass("HindSight Mac agents ingestion key (hidden): ")
    if not token or any(char.isspace() for char in token):
        raise ValueError("No token saved: the key must be nonempty and contain no whitespace.")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    descriptor = os.open(target, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            descriptor = None
            output.write(token)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        target.unlink()
        raise
    finally:
        token = None
    print("Saved HindSight key in ~/.config/hindsight/mac-agents.token (directory 0700, file 0600).")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, getpass.GetPassWarning):
        print("No key saved. Check that the terminal is interactive, storage directories are owned by you, and no token file already exists.", file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print("Cancelled; no key saved.", file=sys.stderr)
        sys.exit(1)
