"""Installer path prompt should recover after stray terminal arrow keys."""
from pathlib import Path
import subprocess
import unittest

SCRIPT=(Path(__file__).resolve().parents[1]/'install.sh').read_text(encoding='utf-8')
START='# Prompt until the input is valid:'
END='if [[ -e "$INSTALL_DIR/app/collector.py" ]]'
assert START in SCRIPT and END in SCRIPT
PROMPT=SCRIPT[SCRIPT.index(START):SCRIPT.index(END)]


class InstallerPromptTests(unittest.TestCase):
    def run_prompt(self,input_value):
        proc=subprocess.run(['bash','-c',PROMPT+'\nprintf "RESULT=%s\\n" "$INSTALL_DIR"'],
            input=input_value,text=True,capture_output=True,timeout=3,check=False)
        return proc

    def test_enter_uses_default(self):
        run=self.run_prompt('\n')
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertIn('RESULT=/opt/pg-traffic-monitor',run.stdout)

    def test_arrow_escape_then_enter_recovers(self):
        run=self.run_prompt('\x1b[A\n\n')
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertIn('Invalid directory',run.stderr)
        self.assertIn('RESULT=/opt/pg-traffic-monitor',run.stdout)

    def test_invalid_relative_then_absolute_path(self):
        run=self.run_prompt('relative/path\n/opt/pgtraffic-demo\n')
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertIn('Invalid directory',run.stderr)
        self.assertIn('RESULT=/opt/pgtraffic-demo',run.stdout)


if __name__=='__main__':
    unittest.main()
