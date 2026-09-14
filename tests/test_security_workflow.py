"""Exercise a complete local authorization investigation with observed fixture results."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CONTROL = Path(__file__).resolve().parents[1] / 'j-space/scripts/control.py'
VULNERABLE = '''def read_record(actor_id, owner_id):
    if actor_id:
        return "fixture-only record"
    raise PermissionError("login required")
'''
FIXED = '''def read_record(actor_id, owner_id):
    if actor_id and actor_id == owner_id:
        return "fixture-only record"
    raise PermissionError("owner required")
'''


class SecurityWorkflowTests(unittest.TestCase):
    def test_local_reproduction_control_fix_and_source_invalidation(self):
        with tempfile.TemporaryDirectory(prefix='jspace authorization ') as directory:
            root = Path(directory)
            (root/'access.py').write_text(VULNERABLE, encoding='utf-8')
            (root/'map.json').write_text(json.dumps({'summary': 'Local authorization fixture',
                'areas': [{'path': 'access.py', 'purpose': 'Owner access check'}]}), encoding='utf-8')

            def cli(*args, allowed=True):
                result = subprocess.run([sys.executable, str(CONTROL), '--root', str(root), *args],
                                        capture_output=True, encoding='utf-8', timeout=30)
                self.assertEqual(result.returncode, 0 if allowed else 2, result.stdout + result.stderr)
                return result

            def observe(actor, name):
                code = ('from access import read_record\n'
                        'try:\n'
                        '    print("RETURN:", read_record(' + repr(actor) + ', "owner"))\n'
                        'except PermissionError as exc:\n'
                        '    print("DENIED:", exc)\n')
                result = subprocess.run([sys.executable, '-B', '-c', code], cwd=root,
                                        capture_output=True, encoding='utf-8', timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                (root/name).write_text('Actor: ' + actor + '\nOwner: owner\n' + result.stdout, encoding='utf-8')
                return result.stdout

            cli('init', '--goal', 'Correct the local owner check', '--next', 'Reproduce access',
                '--level', 'high', '--module', 'modules/cyber.md')
            cli('read')
            self.assertIn('RETURN:', observe('other', 'repro.txt'))
            self.assertIn('RETURN:', observe('owner', 'negative.txt'))
            cli('security', 'add', '--id', 'F1', '--claim', 'A different actor reads an owner record',
                '--scope', 'Local synthetic fixture only', '--repro', 'repro.txt',
                '--negative', 'negative.txt', '--expected', 'A different actor is denied',
                '--observed', 'The fixture record is returned')
            (root/'assessment.txt').write_text('Direct local execution: owner succeeds and another actor also reads the same record; actor_id truthiness omits the owner comparison.', encoding='utf-8')
            cli('security', 'resolve', '--id', 'F1', '--status', 'confirmed', '--evidence', 'assessment.txt')
            (root/'report.txt').write_text('Local authorization defect established by two direct observations.', encoding='utf-8')
            (root/'completion.txt').write_text('The defect is established; repair is still required.', encoding='utf-8')
            cli('report', '--agent', 'root', '--summary', 'Local defect observed', '--evidence', 'report.txt',
                '--completion', 'completion.txt', '--source', 'access.py', '--round', '1', '--next', 'Repair owner condition')
            cli('repo', 'sync', '--map', 'map.json')
            cli('repo', 'view')
            cli('check', '--stage', 'ship', allowed=False)

            (root/'access.py').write_text(FIXED, encoding='utf-8')
            self.assertIn('DENIED:', observe('other', 'fixed-repro.txt'))
            self.assertIn('RETURN:', observe('owner', 'fixed-control.txt'))
            (root/'fix.txt').write_text((root/'fixed-repro.txt').read_text(encoding='utf-8') +
                                       (root/'fixed-control.txt').read_text(encoding='utf-8'), encoding='utf-8')
            cli('security', 'resolve', '--id', 'F1', '--status', 'fixed', '--evidence', 'fix.txt')
            cli('repo', 'sync', '--map', 'map.json')
            cli('repo', 'view')
            cli('check', '--stage', 'ship', allowed=False)  # The old source-bound report is stale.
            (root/'final-report.txt').write_text('Owner-only access restored; direct fixture observations retained.', encoding='utf-8')
            (root/'final-completion.txt').write_text('Goal met for the local fixture: other actor denied, owner allowed. No external service tested.', encoding='utf-8')
            cli('report', '--agent', 'root', '--summary', 'Owner boundary repaired', '--evidence', 'final-report.txt',
                '--completion', 'final-completion.txt', '--source', 'access.py', '--round', '1', '--next', 'Deliver scoped result')
            cli('repo', 'sync', '--map', 'map.json')
            cli('repo', 'view')
            cli('check', '--stage', 'ship')


if __name__ == '__main__':
    unittest.main()
