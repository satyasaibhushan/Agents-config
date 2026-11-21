import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


class CliHelpTest(unittest.TestCase):
    def test_help_exits_without_changing_files(self):
        for script in ('install-shell.py', 'development-access.py'):
            for flag in ('--help', '-h'):
                with self.subTest(script=script, flag=flag), tempfile.TemporaryDirectory() as temp_dir:
                    directory = Path(temp_dir)
                    home = directory / 'home'
                    home.mkdir()
                    zsh_dir = directory / 'zsh'
                    zsh_dir.mkdir()
                    result = subprocess.run(
                        [sys.executable, str(SCRIPTS / script), flag],
                        cwd=directory,
                        env={**os.environ, 'HOME': str(home), 'ZDOTDIR': str(zsh_dir)},
                        capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertTrue(result.stdout.startswith(f'usage: {script} '), result.stdout)
                    self.assertCountEqual(directory.rglob('*'), [home, zsh_dir])
