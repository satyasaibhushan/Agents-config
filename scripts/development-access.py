#!/usr/bin/env python3
"""Apply the explicitly approved development permissions from canonical config."""
import json
import re
import runpy
import tomllib
from datetime import datetime
from pathlib import Path

root = Path(__file__).resolve().parents[1]
api = runpy.run_path(str(root / 'scripts/apply.py'))
home = Path.home()
profile_name = json.loads((home / '.config/agents-config/config.json').read_text())['profile']
profile = {**api['load_profiles']()[profile_name], 'name': profile_name}
api['run_preflight'](profile)
policy = json.loads((root / 'Permissions/development.json').read_text())
if profile_name not in policy['profiles']:
    raise SystemExit('Development permission profile is not enabled for this account')
code_root = str(Path(profile['code_root']).expanduser())
policy['directories'] = policy.pop('directories_by_profile', {}).get(profile_name, policy['directories'])
policy['directories'] = [v.replace('${CODE_ROOT}', code_root).replace('${HOME}', str(home)) for v in policy['directories']]
shared_workflows = root.parent / 'Workflows'
if profile['platform'] == 'linux' and shared_workflows.is_dir():
    policy['directories'].append(str(shared_workflows))
stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
def write(path, content):
    api['backup'](path, home, stamp)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(0o600)
path = home / '.config/agents-config/development.json'
write(path, json.dumps(policy, indent=2)+'\n')
path = home / '.claude/settings.json'
settings = json.loads(path.read_text()) if path.exists() else {}
permissions = settings.setdefault('permissions', {})
permissions['allow'] = list(dict.fromkeys([v for v in permissions.get('allow', []) if v != 'mcp__*'] + policy['allow']))
permissions['additionalDirectories'] = list(dict.fromkeys(permissions.get('additionalDirectories', []) + policy['directories']))
write(path, json.dumps(settings, indent=2)+'\n')
path = home / '.codex/config.toml'
content = path.read_text() if path.exists() else ''
# Preserve unrelated tables and top-level choices. Only manage the workspace sandbox.
sandbox = tomllib.loads(content).get('sandbox_workspace_write', {})
sandbox.update(writable_roots=policy['directories'], network_access=policy['network_access'])
content = re.sub(r'(?ms)^\[sandbox_workspace_write\]\s*\n.*?(?=^\[|\Z)', '', content)
serialize = api['load_genmod']().toml_value
content += '\n[sandbox_workspace_write]\n'+''.join(k+' = '+serialize(v)+'\n' for k,v in sandbox.items())
write(path, content)
print('Applied canonical development permissions for', profile_name)
# Reuse the canonical reconciler for provider instructions and skill discovery.
targets, default_source = api['load_instruction_targets']()
writes = []
for provider in ['claude-code', 'codex']:
    entry = targets[provider]
    content, _ = api['render_instruction'](api['instruction_sources'](entry, profile, default_source))
    writes.append((provider, api['instruction_path'](entry['path'], home), content))
api['write_instruction_files'](writes, home, stamp)
skill_targets = api['load_skill_targets'](api['load_profiles']())
items, canonical = api['plan_skills'](home, skill_targets, profile)
operations = []
for name, cells in items.items():
    for client, cell in cells.items():
        if name in canonical and cell['state'] in (api['MISSING'], api['MIGRATE']):
            operations.append(('link', name, client, api['CANONICAL_SKILLS']/name, home/api['SKILL_AGENTS'][client]/name))
api['apply_skill_ops'](operations, home, stamp)
print('Canonical instructions rendered; linked', len(operations), 'missing or migrated skills')
