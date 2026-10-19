import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('sync_guidelines', Path(__file__).resolve().parents[1] / 'scripts/sync-guidelines.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class GuidelinesTests(unittest.TestCase):
    def test_schedule_preserves_other_jobs_and_replaces_own_job(self):
        old = '0 1 * * * backup\n30 7 * * * old ' + sync.MARKER + '\n'
        new = sync.cron_content(old, '/sync')
        self.assertEqual(new, '0 1 * * * backup\n30 7 * * * /sync ' + sync.MARKER + '\n')
        self.assertEqual(sync.cron_content(new, '/sync'), new)

    def test_cron_escapes_percent(self):
        self.assertIn(r'/a\%b', sync.cron_content('', '/a%b'))

    def test_dirty_cache_is_not_mutated(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(sync, 'run', return_value=' M file') as run:
            with self.assertRaisesRegex(ValueError, 'local edits'):
                sync.prepare_cache(Path(directory))
            self.assertEqual(run.call_count, 1)

    def test_conflict_aborts_own_merge_without_repointing_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def run(*args):
                command = args[3:]
                calls.append(command)
                if command == ('branch', '--show-current'):
                    return 'master'
                if command == ('remote', 'get-url', 'origin'):
                    return sync.UPSTREAM
                if command == ('merge', '--no-edit', 'FETCH_HEAD'):
                    raise subprocess.CalledProcessError(1, args, stderr='conflict')
                return ''
            with patch.object(sync, 'run', side_effect=run):
                with self.assertRaises(subprocess.CalledProcessError):
                    sync.prepare_cache(Path(directory))
            self.assertEqual(calls[-1], ('merge', '--abort'))
            self.assertFalse(any(command[:2] == ('remote', 'set-url') for command in calls))
