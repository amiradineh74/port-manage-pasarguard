"""Public dashboard port prompt retries without changing existing configuration."""
import subprocess
from pathlib import Path
import unittest

script=(Path(__file__).resolve().parents[1]/'publish.sh').read_text(encoding='utf-8')
start='# PORT_SELECTION_START'
end='# PORT_SELECTION_END'
assert start in script and end in script
selection=script[script.index(start):script.index(end)]

# Stub OS-only queries. No real systemd, listening sockets or config changes.
harness=r'''
set -Eeuo pipefail
CURRENT_PORT=8791
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
ss() {
  case "$*" in
    *":8791"*) printf 'LISTEN 0 128 127.0.0.1:8791 0.0.0.0:* users:(("python3",pid=%s,fd=3))\n' "${MOCK_PORT_8791_PID:-1234}" ;;
    *":9000"*) printf 'LISTEN 0 128 0.0.0.0:9000 0.0.0.0:* users:(("other",pid=4321,fd=3))\n' ;;
    *) : ;;
  esac
}
systemctl() {
  if [[ "$1" == 'show' ]]; then printf '1234\n'; else return 1; fi
}
'''
class PublishPortTests(unittest.TestCase):
    def run_choice(self,inputs,env_var=''):
        snippet=harness+('export '+env_var+'\n' if env_var else '')+selection+'\nprintf "RESULT=%s\\n" "$PORT"\n'
        return subprocess.run(['bash','-c',snippet],input=inputs,text=True,capture_output=True,timeout=4,check=False)

    def test_current_monitor_listener_can_be_reused(self):
        p=self.run_choice('\n')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('used by THIS monitor',p.stdout)
        self.assertIn('RESULT=8791',p.stdout)

    def test_other_owner_of_current_port_gets_another_prompt(self):
        p=self.run_choice('\n9001\n','MOCK_PORT_8791_PID=9999')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('occupied by another service',p.stdout)
        self.assertIn('RESULT=9001',p.stdout)

    def test_other_busy_port_then_free_port(self):
        p=self.run_choice('9000\n9002\n')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('occupied by another service',p.stdout)
        self.assertIn('RESULT=9002',p.stdout)

    def test_invalid_values_are_retried(self):
        p=self.run_choice('hello\n0\n99999\n09001\n')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(p.stdout.count('Invalid port'),3)
        self.assertIn('RESULT=9001',p.stdout)

    def test_eof_cancels_cleanly(self):
        p=self.run_choice('')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('Port selection cancelled',p.stderr)

if __name__=='__main__':
    unittest.main()
