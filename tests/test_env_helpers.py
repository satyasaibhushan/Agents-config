from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class EnvHelpersTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        subprocess.run(
            [sys.executable, str(ROOT / 'scripts/install-shell.py')],
            env={**os.environ, 'HOME': str(self.home), 'ZDOTDIR': str(self.home)},
            check=True, capture_output=True,
        )
        self.file = self.home / 'app.env'

    def run_helper(self, name, *args, stdin=None, file=None):
        return subprocess.run(
            [str(self.home / '.local/bin' / name), str(file or self.file), *args],
            env={**os.environ, 'PATH': str(Path(sys.executable).parent) + os.pathsep + os.environ['PATH']},
            input=stdin, text=True, capture_output=True,
        )

    def test_keys_only_and_optional_glob(self):
        self.file.write_text(
            '\ufeff# PRETEND=ignored\nexport API_HOST = example.test\n'
            'SECRET="one\ntwo\nPRETEND_URL=hidden-secret"\nEMPTY=\n'
        )
        keys = self.run_helper('env-keys')
        self.assertEqual((keys.returncode, keys.stdout, keys.stderr),
                         (0, 'API_HOST\nSECRET\nEMPTY\n', ''))
        filtered = self.run_helper('env-keys', 'API_*')
        self.assertEqual((filtered.returncode, filtered.stdout, filtered.stderr),
                         (0, 'API_HOST\n', ''))

    def test_hosts_mask_credentials_and_other_values(self):
        self.file.write_text(
            'DB_URL="postgres://db-user:db-password@db.test:5432/secret-path?token=secret-query#secret-fragment"\n'
            'CACHE_HOST=cache.test:6379\n'
            'API_BASE=//account:password@[::1]:8443/api\n'
            'BACKUP_URL=account:password@backup.test/path\n'
            'SECRET=hidden-secret\n'
            'API_URL_EXTRA=https://hidden.test\n'
            'MALFORMED_URL=https://db.test:secret-port\n'
            'EXPANDED_URL="https://${PASSWORD}/api"\n'
        )
        result = self.run_helper('env-hosts')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout, (
            'DB_URL=postgres://[redacted]@db.test:5432\n'
            'CACHE_HOST=cache.test:6379\n'
            'API_BASE=//[redacted]@[::1]:8443\n'
            'BACKUP_URL=[redacted]@backup.test\n'
            'SECRET=[redacted]\n'
            'API_URL_EXTRA=[redacted]\n'
            'MALFORMED_URL=[redacted]\n'
            'EXPANDED_URL=[redacted]\n'
        ))

    def test_suffix_updates_one_key_and_preserves_file_format(self):
        original = b'# service\r\nexport API_URL = "https://user:pass@old.test/uat" # routing\r\nKEY=secret\r\n'
        self.file.write_bytes(original)
        self.file.chmod(0o640)
        inode = self.file.stat().st_ino
        result = self.run_helper('env-set', 'API_URL', '--replace-suffix', 'old.test/uat', 'new.test/dev')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'Updated API_URL in {self.file}\n', ''))
        self.assertEqual(
            self.file.read_bytes(),
            original.replace(b'"https://user:pass@old.test/uat"', b'https://user:pass@new.test/dev'),
        )
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o640)
        self.assertNotEqual(self.file.stat().st_ino, inode)
        self.assertEqual(list(self.home.glob('.env-set-*')), [])

    def test_value_and_stdin_do_not_echo_secrets(self):
        self.file.write_bytes(b'KEEP=yes')
        secret = 'new secret # with spaces'
        options = [('--value', secret), ('--stdin',)]
        for args in options:
            with self.subTest(mode=args[0]):
                result = self.run_helper('env-set', 'PASSWORD', *args, stdin=secret + '\r\n')
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (0, f'Updated PASSWORD in {self.file}\n', ''))
                self.assertEqual(self.file.read_text(), f"KEEP=yes\nPASSWORD='{secret}'\n")

    def test_bad_inputs_leave_original_intact_and_hide_arguments(self):
        self.file.write_text('SAFE=old\nREPEATED=one\nREPEATED=two\n')
        original = self.file.read_bytes()
        for args in (
            ('SAFE', '--replace-suffix', 'secret-suffix', 'new-secret'),
            ('MISSING', '--replace-suffix', 'old', 'new-secret'),
            ('SAFE', '--value', 'new-secret\nOTHER=bad'),
            ('SAFE', '--value', 'new-secret', 'unexpected-secret'),
            ('REPEATED', '--value', 'new-secret'),
        ):
            with self.subTest(mode=args[:2]):
                result = self.run_helper('env-set', *args)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                self.assertNotIn('secret', result.stderr)
                self.assertEqual(self.file.read_bytes(), original)

    def test_unsupported_syntax_fails_before_printing(self):
        self.file.write_text('VISIBLE_HOST=visible.test\nSECRET=hidden\\\nHIDDEN_HOST=hidden.test\n')
        for name in ('env-keys', 'env-hosts'):
            result = self.run_helper(name)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertNotIn('hidden', result.stderr)

    def test_symlinks_and_non_dotenv_filenames_are_refused(self):
        target = self.home / 'secret.txt'
        target.write_text('DATABASE_URL=https://hidden.test\n')
        self.file.symlink_to(target)
        for name, args in (
            ('env-keys', ()), ('env-hosts', ()), ('env-set', ('DATABASE_URL', '--value', 'new')),
        ):
            for file in (self.file, target):
                with self.subTest(name=name, file=file.name):
                    result = self.run_helper(name, *args, file=file)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, '')
                    self.assertNotIn('hidden.test', result.stderr)
        self.assertTrue(self.file.is_symlink())
        self.assertEqual(target.read_text(), 'DATABASE_URL=https://hidden.test\n')

    def test_concurrent_updates_keep_every_key(self):
        self.file.write_text('KEEP=original\n')
        keys = [f'WORKER_{index}' for index in range(8)]
        with ThreadPoolExecutor(max_workers=len(keys)) as pool:
            results = list(pool.map(lambda key: self.run_helper('env-set', key, '--value', 'updated'), keys))
        self.assertEqual([(r.returncode, r.stderr) for r in results], [(0, '')] * len(keys))
        self.assertCountEqual(self.file.read_text().splitlines(),
                              ['KEEP=original'] + [f'{key}=updated' for key in keys])
