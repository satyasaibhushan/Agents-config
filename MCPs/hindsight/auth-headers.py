#!/usr/bin/python3
"""Private MCP header helper. Stdout belongs only to the invoking MCP client."""
import json
import os
from pathlib import Path
import stat
import sys

ENDPOINT = "https://hindsight.bhushan.fun/api/mcp"


def check_owner(info):
    if info.st_uid != os.getuid():
        raise ValueError("Unsafe ownership")


def token():
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptors = []
    try:
        home = os.open(Path.home(), flags)
        descriptors.append(home)
        check_owner(os.fstat(home))
        config = os.open(".config", flags, dir_fd=home)
        descriptors.append(config)
        check_owner(os.fstat(config))
        folder = os.open("hindsight", flags, dir_fd=config)
        descriptors.append(folder)
        info = os.fstat(folder)
        check_owner(info)
        if stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("Unsafe directory permissions")
        descriptor = os.open("mac-agents.token", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=folder)
        descriptors.append(descriptor)
        info = os.fstat(descriptor)
        check_owner(info)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
            raise ValueError("Unsafe token file")
        if not 0 < info.st_size <= 8192:
            raise ValueError("Invalid token size")
        key = os.read(descriptor, 8193).decode("utf-8")
        if not key or any(c.isspace() for c in key):
            raise ValueError("Invalid token contents")
        return key
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def main():
    if sys.stdout.isatty() or len(sys.argv) != 1:
        raise ValueError("Client pipe required")
    if os.environ.get("CLAUDE_CODE_MCP_SERVER_NAME") != "hindsight":
        raise ValueError("Wrong server")
    if os.environ.get("CLAUDE_CODE_MCP_SERVER_URL") != ENDPOINT:
        raise ValueError("Wrong endpoint")
    key = token()
    sys.stdout.write(json.dumps({"Authorization": "Bearer " + key}) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        # No arbitrary exception, path, header, or token data is rendered.
        sys.stderr.write("HindSight authentication helper could not run safely.\n")
        sys.exit(1)
