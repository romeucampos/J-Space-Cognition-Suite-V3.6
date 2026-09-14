import json
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'j-space' / 'scripts'
SPEC = importlib.util.spec_from_file_location('sv1_bridge', SCRIPTS / 'host_bridge.py')
BRIDGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BRIDGE)


class HostBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='jspace bridge ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def bridge(self, payload):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / 'host_bridge.py'), '--root', str(self.root)],
            input=payload, capture_output=True, encoding='utf-8', check=False,
        )
        return result, json.loads(result.stdout)

    def initialize(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / 'control.py'), '--root', str(self.root),
             'init', '--goal', 'Deliver evidence', '--next', 'Inspect sources', '--level', 'high'],
            capture_output=True, encoding='utf-8', check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_uninitialized_task_is_blocked(self):
        result, reply = self.bridge('{"event":"before_work"}')
        self.assertEqual(result.returncode, 2)
        self.assertFalse(reply['allow'])

    def test_timeout_is_trusted_config_and_applies_to_both_subprocesses(self):
        result = subprocess.CompletedProcess([], 0, 'context', '')
        with patch.object(BRIDGE.subprocess, 'run', return_value=result) as runner:
            reply = BRIDGE.handle(self.root, {'event': 'before_work'}, timeout=240)
            self.assertTrue(reply['allow'])
            self.assertEqual(runner.call_count, 2)
            self.assertTrue(all(call.kwargs['timeout'] == 240 for call in runner.call_args_list))
        for timeout in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                BRIDGE.handle(self.root, {'event': 'resume'}, timeout=timeout)
        with self.assertRaises(ValueError):
            BRIDGE.handle(self.root, {'event': 'resume', 'timeout': 240})

    def test_timeout_cli_validation_and_actual_deadline_fail_closed(self):
        self.initialize()
        for timeout in ('nan', 'inf', '0', '-1', '0.000001'):
            result = subprocess.run([sys.executable, str(SCRIPTS / 'host_bridge.py'), '--root', str(self.root),
                                     '--timeout-seconds', timeout], input='{"event":"before_work"}',
                                    capture_output=True, encoding='utf-8')
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertFalse(json.loads(result.stdout)['allow'])

    def test_resume_injects_actual_entry(self):
        self.initialize()
        result, reply = self.bridge('{"event":"resume"}')
        self.assertEqual(result.returncode, 0, reply)
        self.assertTrue(reply['allow'])
        entry = (SCRIPTS.parent / 'SKILL.md').read_text(encoding='utf-8')
        self.assertIn(entry.strip(), reply['context'])

    def test_unknown_agent_and_malformed_events_fail_closed(self):
        self.initialize()
        for payload in ('{}', '[]', 'null', '{"event":[]}', '{"event":"resume","root":".."}',
                        '{"event":"resume","agent":"missing"}', 'bad json', 'x' * 65537):
            with self.subTest(payload=payload[:90]):
                result, reply = self.bridge(payload)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(reply['allow'])

    def test_repo_drift_blocks_work_and_repair_events_remain_available(self):
        self.initialize()
        (self.root/'map.json').write_text('{"summary":"test","areas":[{"path":"source.txt","purpose":"fixture"}]}', encoding='utf-8')
        (self.root/'source.txt').write_text('initial', encoding='utf-8')
        for args in [('repo', 'sync', '--map', 'map.json'), ('repo', 'view')]:
            result = subprocess.run([sys.executable, str(SCRIPTS/'control.py'), '--root', str(self.root), *args], capture_output=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.bridge('{"event":"resume"}')
        result, reply = self.bridge('{"event":"before_work"}')
        self.assertEqual(result.returncode, 0, reply)
        (self.root/'source.txt').write_text('changed', encoding='utf-8')
        result, reply = self.bridge('{"event":"before_work"}')
        self.assertEqual(result.returncode, 2)
        self.assertFalse(reply['allow'])
        result, reply = self.bridge('{"event":"failure"}')
        self.assertEqual(result.returncode, 0, reply)
        self.assertTrue(reply['allow'])


if __name__ == '__main__':
    unittest.main()
