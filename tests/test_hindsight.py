import importlib.util
import json
from pathlib import Path
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]

class FeedbackSetupTest(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('feedback_setup',ROOT/'scripts/install-hindsight.py')
        self.setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.setup)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name)

    def test_idempotent_preserving_settings(self):
        for client,text in [('codex','model = "existing"\n[mcp_servers.other]\ncommand="other"\n'),('cursor','{"approvals":"existing","mcpServers":{"other":{"command":"other"}}}'),('claude-code','{"projects":{"private":{}},"mcpServers":{}}'),('opencode','{ // keep comment\n "model":"existing",\n}')]:
            desired=self.setup.registration(self.home,client)
            after=self.setup.add_entry(text,client,desired)
            self.assertEqual(after,self.setup.add_entry(after,client,desired))
            if client=='opencode': self.assertIn('// keep comment',after)
            before=tomllib.loads(text) if client=='codex' else self.setup.jsonc_data(text)
            parsed=tomllib.loads(after) if client=='codex' else self.setup.jsonc_data(after)
            key='mcp_servers' if client=='codex' else 'mcp' if client=='opencode' else 'mcpServers'
            parsed[key].pop('hindsight')
            if key not in before: parsed.pop(key)
            self.assertEqual(before,parsed)

    def test_conflicting_entry_refused(self):
        for client in ['cursor','claude-code','opencode']:
            key='mcp' if client=='opencode' else 'mcpServers'
            with self.assertRaises(ValueError):
                self.setup.add_entry(json.dumps({key:{'hindsight':{'command':'unrelated'}}}),client,self.setup.registration(self.home,client))
        with self.assertRaises(ValueError):
            self.setup.add_entry('[mcp_servers.hindsight]\ncommand="unrelated"','codex',self.setup.registration(self.home,'codex'))

    def test_jsonc_existing_map_not_rewritten(self):
        with self.assertRaises(ValueError):
            self.setup.add_entry('{/* retained */ "mcp":{"other":{}}}', 'opencode', self.setup.registration(self.home,'opencode'))

    def test_helpers_reject_symlink_destination(self):
        target=self.home/'target';target.write_text('preserve')
        link=self.home/'link';link.symlink_to(target)
        with self.assertRaises(ValueError): self.setup.write(link,'replacement')
        self.assertEqual(target.read_text(),'preserve')

    def test_definition_is_mac_only_and_has_one_transport(self):
        spec=importlib.util.spec_from_file_location('generator',ROOT/'MCPs/scripts/generate-mcps.py')
        gen=importlib.util.module_from_spec(spec);spec.loader.exec_module(gen)
        entry=json.loads((ROOT/'MCPs/servers.json').read_text())['servers']['hindsight']
        self.assertEqual(entry['profiles'],['mac-admin'])
        self.assertEqual(entry['platforms'],['darwin'])
        for client in entry['clients']:
            if client=='codex': result=gen.codex_server_config(entry,{'HOME':str(self.home)})
            else: result=gen.json_config_for_client({'hindsight':entry},client,{'HOME':str(self.home)})['mcpServers']['hindsight']
            self.assertEqual(result,self.setup.registration(self.home,client))
