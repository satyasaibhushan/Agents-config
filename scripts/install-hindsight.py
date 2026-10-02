#!/usr/bin/env python3
"""Install the Mac feedback runtime and only its entries; never open the key."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'MCPs/hindsight'
ENDPOINT = 'https://hindsight.bhushan.fun/api/mcp'


def owned(path, directory=False):
    info = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError('Expected a real, owner-controlled path: ' + str(path))
    return info


def mkdir(path, private=False):
    if not path.exists():
        mkdir(path.parent)
        path.mkdir(mode=0o700)
    owned(path, directory=True)
    if private:
        path.chmod(0o700)


def write(path, content, mode=0o600):
    mkdir(path.parent)
    if path.exists() or path.is_symlink():
        owned(path)
    fd, temp = tempfile.mkstemp(prefix='.hindsight-', dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def uncomment(text):
    # Preserve character positions; ignore JSONC comment contents and strings.
    chars = list(text)
    i = 0
    inside = False
    escaped = False
    while i < len(chars):
        c = chars[i]
        if inside:
            if escaped: escaped = False
            elif c == "\\": escaped = True
            elif c == '"': inside = False
            i += 1
        elif c == '"':
            inside = True
            i += 1
        elif text.startswith("//", i):
            while i < len(chars) and chars[i] != "\n":
                chars[i] = " "
                i += 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0: raise RuntimeError("Invalid JSONC comment.")
            for j in range(i, end + 2):
                if chars[j] != "\n": chars[j] = " "
            i = end + 2
        else:
            i += 1
    return "".join(chars)

def jsonc_data(text):
    plain = uncomment(text)
    chars = list(plain)
    inside = escaped = False
    for i, c in enumerate(plain):
        if inside:
            if escaped: escaped = False
            elif c == "\\": escaped = True
            elif c == '"': inside = False
        elif c == '"': inside = True
        elif c == ",":
            j = i + 1
            while j < len(plain) and plain[j].isspace(): j += 1
            if j < len(plain) and plain[j] in "}]": chars[i] = " "
    return json.loads("".join(chars))

def registration(home, client):
    if client == 'claude-code':
        return {'type':'http', 'url':ENDPOINT,
                'headersHelper':str(home / '.local/bin/hindsight-auth-headers')}
    if client == 'opencode':
        return {'type':'remote', 'url':ENDPOINT, 'oauth':False,
                'headers':{'Authorization':'Bearer {file:~/.config/hindsight/mac-agents.token}'}}
    return {'command':str(home / '.local/bin/hindsight-mcp')}


def add_entry(text, client, desired):
    if client == 'codex':
        data = tomllib.loads(text)
        old = data.get('mcp_servers', {}).get('hindsight')
        if old == desired: return text
        if old is not None: raise ValueError('Existing HindSight entry differs; reconcile explicitly')
        result = text.rstrip() + '\n\n[mcp_servers.hindsight]\ncommand = ' + json.dumps(desired['command']) + '\n'
        parsed = tomllib.loads(result)
        parsed['mcp_servers'].pop('hindsight')
        if not parsed['mcp_servers'] and 'mcp_servers' not in data: parsed.pop('mcp_servers')
        if parsed != data: raise ValueError('Unrelated configuration changed')
        return result
    if client == 'opencode':
        data = jsonc_data(text)
        old = data.get('mcp', {}).get('hindsight')
        if old == desired: return text
        if old is not None: raise ValueError('Existing HindSight entry differs; reconcile explicitly')
        if 'mcp' in data:
            raise ValueError('Existing OpenCode MCP map requires explicit native merge')
        end = uncomment(text).rfind('}')
        preceding = uncomment(text)[:end].rstrip()
        comma = '' if preceding.endswith(('{', ',')) else ','
        result = text[:end] + comma + '\n  "mcp": ' + json.dumps({'hindsight':desired},indent=2) + '\n' + text[end:]
        check = jsonc_data(result); check.pop('mcp')
        if check != data: raise ValueError('Unrelated configuration changed')
        return result
    data = json.loads(text)
    key = 'mcpServers'
    old = data.get(key, {}).get('hindsight')
    if old == desired: return text
    if old is not None: raise ValueError('Existing HindSight entry differs; reconcile explicitly')
    data.setdefault(key, {})['hindsight'] = desired
    return json.dumps(data, indent=2) + '\n'


def config_paths(home):
    targets = [('codex', home / '.codex/config.toml'),
               ('claude-code', home / '.claude.json'),
               ('cursor', home / '.cursor/mcp.json'),
               ('opencode', home / '.config/opencode/opencode.jsonc')]
    # Only existing hub profiles are enrolled. Never create another machine's profile.
    for suffix in ('zai', 'copilot', 'cursor'):
        p = home / ('.codex-privatehub-' + suffix) / 'config.toml'
        if p.exists(): targets.append(('codex', p))
    p = home / '.claude-privatehub/.claude.json'
    if p.exists(): targets.append(('claude-code', p))
    return targets


def install(home, instructions=False):
    binpath = home / '.local/bin'; mkdir(binpath)
    write(binpath / 'save-hindsight-token', (SOURCE / 'save-token.py').read_text(), 0o700)
    keydir = home / '.config/hindsight'
    if not (keydir / 'mac-agents.token').exists():
        raise ValueError('Local key missing. Run ~/.local/bin/save-hindsight-token in your terminal, then repeat installation')
    info = owned(keydir, directory=True)
    if stat.S_IMODE(info.st_mode) != 0o700: raise ValueError('Key directory must have mode 0700')
    info = owned(keydir / 'mac-agents.token')
    if stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
        raise ValueError('Key must have mode 0600 and one link')
    node = shutil.which('node')
    if not node: raise ValueError('Install Node 22 or newer first')
    version = subprocess.run([node,'--version'], capture_output=True, text=True, check=True).stdout.strip()
    if int(version.lstrip('v').split('.')[0]) < 22: raise ValueError('Node 22 or newer required')
    base = home / '.local/share/hindsight-mcp'
    updates = []
    for client,path in config_paths(home):
        old = path.read_text() if path.exists() and owned(path) else ('' if client == 'codex' else '{}')
        new = add_entry(old, client, registration(home, client))
        if new != old: updates.append((path, old, new))
    mkdir(base, private=True)
    manifest = (SOURCE / 'package.json').read_text()
    lock = (SOURCE / 'package-lock.json').read_text()
    sdk = base / 'node_modules/@modelcontextprotocol/sdk/package.json'
    installed = sdk.exists() and json.loads(sdk.read_text()).get('version') == '1.30.0'
    locked = (base / 'package-lock.json').exists() and (base / 'package-lock.json').read_text() == lock
    write(base / 'package.json', manifest)
    write(base / 'package-lock.json', lock)
    if not (installed and locked):
        npm = shutil.which('npm')
        if not npm: raise ValueError('Install npm first')
        env = os.environ.copy(); env.pop('HINDSIGHT_INGEST_TOKEN', None)
        result = subprocess.run([npm,'ci','--ignore-scripts','--no-audit','--no-fund','--prefix',str(base)], env=env, capture_output=True, timeout=120)
        if result.returncode: raise ValueError('Locked dependency installation failed; diagnostics suppressed')
    write(base / 'bridge.mjs', (SOURCE / 'bridge.mjs').read_text())
    binpath = home / '.local/bin'; mkdir(binpath)
    write(binpath / 'hindsight-auth-headers', (SOURCE / 'auth-headers.py').read_text(), 0o700)
    write(binpath / 'save-hindsight-token', (SOURCE / 'save-token.py').read_text(), 0o700)
    write(binpath / 'hindsight-mcp', '#!/bin/sh\nexec ' + shlex.quote(node) + ' ' + shlex.quote(str(base / 'bridge.mjs')) + ' "$@"\n', 0o700)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-hindsight'
    backups = home / '.local/state/agents-config/backups' / stamp
    for i,(path,old,new) in enumerate(updates):
        if path.exists() and path.read_text() != old: raise ValueError('Configuration changed concurrently')
        mkdir(backups, private=True); write(backups / (str(i)+'.backup'),old)
        write(path,new)
    print('HindSight runtime installed; registered ' + str(len(config_paths(home))) + ' profiles; changed ' + str(len(updates)) + ' configs. Key contents never opened.')
    if instructions:
        spec = importlib.util.spec_from_file_location('reconcile', ROOT / 'scripts/apply.py')
        apply = importlib.util.module_from_spec(spec); spec.loader.exec_module(apply)
        profile = apply.load_profiles()['mac-admin']
        targets, default = apply.load_instruction_targets()
        targets['opencode'] = {'path':'~/.config/opencode/AGENTS.md'}
        for suffix in ('zai', 'copilot', 'cursor'):
            folder = '.codex-privatehub-' + suffix
            if (home / folder).is_dir():
                targets['hub-' + suffix] = {'path':'~/' + folder + '/AGENTS.md'}
        if (home / '.claude-privatehub').is_dir():
            targets['hub-primary'] = {'path':'~/.claude-privatehub/CLAUDE.md',
                                      'extra':'providers/claude-code.md'}
        writes = []
        for provider, entry in targets.items():
            sources = apply.instruction_sources(entry, profile, default)
            desired,_ = apply.render_instruction(sources)
            previous,_ = apply.render_instruction([s for s in sources if s != 'fragments/hindsight.md'])
            path = apply.instruction_path(entry['path'], home)
            if path.exists():
                owned(path)
                current = path.read_text()
                if current == desired: continue
                if current != previous: raise ValueError('Instruction drift preserved; reconcile ' + str(path))
            writes.append((provider,path,desired))
        apply.write_instruction_files(writes,home,stamp)
        print('Shared feedback instructions synced to ' + str(len(writes)) + ' targets.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instructions', action='store_true', help='sync only missing or unchanged previous instruction renders')
    args = parser.parse_args()
    if sys.platform != 'darwin': raise ValueError('This registration is restricted to the Mac account')
    os.umask(0o077)
    install(Path.home(),args.instructions)

if __name__ == '__main__':
    try: main()
    except Exception as error:
        # Configuration contents, subprocess output and runtime key are never shown.
        print('HindSight setup stopped: ' + (str(error) if isinstance(error,ValueError) else type(error).__name__),file=sys.stderr)
        sys.exit(1)
