"""Installer discovers the panel container from read-only Docker metadata."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import setup

class ContainerDiscoveryTests(unittest.TestCase):
    def test_docker_ps_read_only(self):
        from subprocess import CompletedProcess
        with patch.object(setup.subprocess,'run',return_value=CompletedProcess([],0,'pasarguard-pasarguard-1\nother\n','')) as run:
            self.assertEqual(setup.running_container_names(),['pasarguard-pasarguard-1','other'])
            self.assertEqual(run.call_args.args[0],['docker','ps','--format','{{.Names}}'])

    def test_auto_detect_only_match(self):
        with patch.object(setup,'running_container_names',return_value=['redis','pasarguard-pasarguard-1']):
            self.assertEqual(setup.select_panel_container({}),'pasarguard-pasarguard-1')

    def test_multiple_matches_numbered_choice(self):
        with patch.object(setup,'running_container_names',return_value=['pasarguard-panel','pasarguard-worker']):
            with patch('builtins.input',return_value='1'):
                self.assertEqual(setup.select_panel_container({}),'pasarguard-panel')

    def test_no_matching_name_asks_user(self):
        with patch.object(setup,'running_container_names',return_value=['my-panel','redis']):
            with patch('builtins.input',return_value='1'):
                self.assertEqual(setup.select_panel_container({}),'my-panel')

    def test_no_running_containers_stops_safely(self):
        with patch.object(setup,'running_container_names',return_value=[]):
            with self.assertRaisesRegex(RuntimeError,'No running Docker'):
                setup.select_panel_container({})

if __name__=='__main__':
    unittest.main()
