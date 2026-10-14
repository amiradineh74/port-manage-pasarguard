from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class SafetyInvariants(unittest.TestCase):
    def test_bridge_does_not_reset(self):
        content=(ROOT/'app'/'bridge.py').read_text()
        self.assertIn('reset=False',content)
        self.assertNotIn('reset=True',content)
        self.assertNotIn('await node.stop(',content)
        self.assertNotIn('await node.start(',content)
    def test_public_publish_only_changes_monitor(self):
        script=(ROOT/'publish.sh').read_text()
        self.assertIn('pgtraffic-web.service',script)
        self.assertIn("cfg['listen_host']='0.0.0.0'",script)
        self.assertIn("cfg['listen_port']=int(sys.argv[2])",script)
        self.assertNotIn('systemctl restart pasarguard',script)
        self.assertNotIn('docker restart',script)
        self.assertNotIn('ufw allow',script)

    def test_no_real_server_ips_in_repo_defaults(self):
        content=(ROOT/'app'/'setup.py').read_text()
        self.assertIn("'node_ids':[]",content)
        self.assertIn("'monitor_all_nodes':False",content)
        self.assertNotIn("'node_ips':[]",content)

if __name__=='__main__':unittest.main()
