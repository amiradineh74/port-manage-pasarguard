"""Public dashboard setup must distinguish its own listener from an occupied port."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT=(Path(__file__).resolve().parents[1]/'publish.sh').read_text(encoding='utf-8')
START='# A first-time publication legitimately reuses the current web listener:'
END="printf '\\n=== Publish dashboard via public HTTP ===\\n'"
assert START in SCRIPT and END in SCRIPT
CHECK=SCRIPT[SCRIPT.index(START):SCRIPT.index(END)]


class PublicPortChecks(unittest.TestCase):
    def run_check(self,listeners='',active='yes',pid='24880',port='8791',current_port='8791'):
        with tempfile.TemporaryDirectory() as tmp:
            ss=Path(tmp)/'ss'
            ss.write_text('#!/usr/bin/env bash\nprintf "%s" "$MOCK_SS"\n')
            ss.chmod(0o755)
            systemctl=Path(tmp)/'systemctl'
            systemctl.write_text('''#!/usr/bin/env bash
case "$1" in
  is-active) [[ "$MOCK_ACTIVE" == yes ]];;
  show) printf '%s\\n' "$MOCK_PID";;
  *) exit 2;;
esac
''')
            systemctl.chmod(0o755)
            env=os.environ.copy()
            env.update(PATH=tmp+os.pathsep+env['PATH'],MOCK_SS=listeners,
                       MOCK_ACTIVE=active,MOCK_PID=pid)
            prelude="""set -Eeuo pipefail
fail() { echo "ERROR: $*" >&2; exit 1; }
CURRENT_HOST=127.0.0.1
CURRENT_PORT="""+current_port+"""
PORT="""+port+"""
"""
            return subprocess.run(['bash','-c',prelude+CHECK+'echo REACHED_PUBLICATION'],
                                  capture_output=True,text=True,env=env,timeout=5)

    def test_free_port_allowed(self):
        run=self.run_check()
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertIn('REACHED_PUBLICATION',run.stdout)

    def test_existing_dashboard_listener_allowed(self):
        listener='LISTEN 0 5 127.0.0.1:8791 0.0.0.0:* users:(("python3",pid=24880,fd=3))'
        run=self.run_check(listener)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertIn('reused safely',run.stdout)

    def test_foreign_listener_blocked(self):
        listener='LISTEN 0 128 127.0.0.1:8791 0.0.0.0:* users:(("other",pid=9090,fd=3))'
        run=self.run_check(listener)
        self.assertNotEqual(run.returncode,0)
        self.assertIn('not owned',run.stderr)

    def test_multiple_listeners_one_foreign_blocked(self):
        own='LISTEN 0 5 127.0.0.1:8791 0.0.0.0:* users:(("python3",pid=24880,fd=3))'
        foreign='LISTEN 0 5 91.107.254.186:8791 0.0.0.0:* users:(("another",pid=3001,fd=3))'
        run=self.run_check(own+'\n'+foreign)
        self.assertNotEqual(run.returncode,0)
        self.assertIn('not owned',run.stderr)

    def test_inactive_dashboard_does_not_allow_listener(self):
        own='LISTEN 0 5 127.0.0.1:8791 0.0.0.0:* users:(("python3",pid=24880,fd=3))'
        run=self.run_check(own,active='no')
        self.assertNotEqual(run.returncode,0)
        self.assertIn('unverified service',run.stderr)

    def test_unknown_process_does_not_allow_listener(self):
        run=self.run_check('LISTEN 0 5 127.0.0.1:8791 0.0.0.0:*')
        self.assertNotEqual(run.returncode,0)

    def test_different_port_occupied_rejected(self):
        foreign='LISTEN 0 5 127.0.0.1:8792 0.0.0.0:* users:(("python3",pid=24880,fd=3))'
        run=self.run_check(foreign,port='8792')
        self.assertNotEqual(run.returncode,0)
        self.assertIn('unverified service',run.stderr)


if __name__=='__main__':
    unittest.main()
