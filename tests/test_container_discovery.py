"""The setup must discover the running panel without knowing Docker names."""
import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import setup


class DockerDiscoveryTests(unittest.TestCase):
    def test_read_only_docker_ps_lists_running_containers(self):
        result=subprocess.CompletedProcess(['docker','ps'],0,
            stdout='pasarguard-postgres-1\npasarguard-pasarguard-1\n',stderr='')
        with patch.object(setup.subprocess,'run',return_value=result) as run:
            names=setup.running_docker_containers()
        self.assertEqual(names,['pasarguard-pasarguard-1','pasarguard-postgres-1'])
        self.assertEqual(run.call_args.args[0],
            ['docker','ps','--format','{{.Names}}'])

    def test_app_not_database_is_recommended(self):
        self.assertTrue(setup.probable_pasarguard_panel('pasarguard-pasarguard-1'))
        for name in ['pasarguard-postgres-1','pasarguard-redis-1',
                     'pasarguard-node-3','pasarguard-db-1']:
            self.assertFalse(setup.probable_pasarguard_panel(name))

    def test_enter_selects_probable_container_and_validates_nodes(self):
        names=['pasarguard-pasarguard-1','pasarguard-postgres-1']
        cfg=dict(setup.DEFAULT)
        with patch.object(setup,'running_docker_containers',return_value=names), \
             patch('builtins.input',return_value=''), \
             patch.object(setup,'ask',return_value='/code/.venv/bin/python'), \
             patch.object(setup,'list_nodes',return_value=[{'id':3,'name':'Turkey'}]) as reader, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            nodes=setup.discover_panel_connection(cfg)
        self.assertEqual(nodes,[{'id':3,'name':'Turkey'}])
        self.assertEqual(cfg['panel_container'],'pasarguard-pasarguard-1')
        reader.assert_called_once_with('pasarguard-pasarguard-1','/code/.venv/bin/python')
        self.assertIn('docker ps',output.getvalue())
        self.assertIn('Dashboard title is asked later',output.getvalue())

    def test_unlisted_dashboard_name_is_reprompted(self):
        names=['pasarguard-pasarguard-1','pasarguard-postgres-1']
        cfg=dict(setup.DEFAULT)
        with patch.object(setup,'running_docker_containers',return_value=names), \
             patch('builtins.input',side_effect=['manage usage port','']), \
             patch.object(setup,'ask',return_value='/code/.venv/bin/python'), \
             patch.object(setup,'list_nodes',return_value=[{'id':7,'name':'Germany'}]), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            setup.discover_panel_connection(cfg)
        self.assertIn('Unknown container',output.getvalue())
        self.assertEqual(cfg['panel_container'],'pasarguard-pasarguard-1')

    def test_invalid_panel_probe_can_choose_another_container(self):
        cfg=dict(setup.DEFAULT)
        cfg['panel_container']='previous-deleted-container'
        with patch.object(setup,'running_docker_containers',return_value=[
                'pasarguard-app-1','pasarguard-db-1']), \
             patch('builtins.input',side_effect=['2','1']), \
             patch.object(setup,'ask',return_value='/code/.venv/bin/python'), \
             patch.object(setup,'list_nodes',side_effect=[
                RuntimeError('Could not read PasarGuard node list from the panel container.'),
                [{'id':7,'name':'Germany'}]]) as reader, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            nodes=setup.discover_panel_connection(cfg)
        self.assertEqual(nodes,[{'id':7,'name':'Germany'}])
        self.assertEqual(cfg['panel_container'],'pasarguard-app-1')
        self.assertEqual(reader.call_count,2)
        self.assertIn('Choose another listed container',output.getvalue())

    def test_multiple_non_obvious_containers_require_explicit_selection(self):
        cfg=dict(setup.DEFAULT)
        with patch.object(setup,'running_docker_containers',return_value=['custom-panel','backup-service']), \
             patch('builtins.input',side_effect=['','2']), \
             patch.object(setup,'ask',return_value='/code/.venv/bin/python'), \
             patch.object(setup,'list_nodes',return_value=[{'id':9,'name':'Node'}]), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            setup.discover_panel_connection(cfg)
        self.assertEqual(cfg['panel_container'],'custom-panel')
        self.assertIn('Select a number',output.getvalue())


if __name__=='__main__':
    unittest.main()
