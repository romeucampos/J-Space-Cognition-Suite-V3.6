"""End-to-end checks for the SV1 cooperative controller; no external services."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'j-space' / 'scripts' / 'control.py'
SPEC = importlib.util.spec_from_file_location('sv1_control', SCRIPT)
CONTROL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTROL)


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='j space 中文 ')
        self.root = Path(self.temp.name).resolve()
        self.write('src/code.py', 'value = 1\n')
        self.write('map.json', json.dumps({'summary': 'Task architecture', 'areas': [
            {'path': 'src', 'purpose': 'Application code', 'dependencies': [], 'tests': ['tests']}],
            'facts': [{'claim': 'Code defines a value', 'evidence': 'src/code.py'}],
            'unknowns': ['No runtime assertion yet']}, ensure_ascii=False))

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return path

    def cli(self, *args, ok=True):
        result = subprocess.run([sys.executable, str(SCRIPT), '--root', str(self.root), *args],
                                capture_output=True, text=True, encoding='utf-8', timeout=25)
        self.assertEqual(result.returncode, 0 if ok else 2, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def state(self):
        return json.loads((self.root / '.jspace/control.json').read_text(encoding='utf-8'))

    def replace_state(self, state):
        (self.root / '.jspace/control.json').write_text(json.dumps(state), encoding='utf-8')

    def init(self, *extra):
        self.cli('init', '--goal', '正确完成任务', '--next', 'Read code', '--level', 'high', *extra)

    def prepare(self):
        self.init()
        self.cli('pulse', '--event', 'resume')
        self.sync()

    def sync(self):
        self.cli('repo', 'sync', '--map', 'map.json')
        self.cli('repo', 'view')
        for aid, agent in self.state()['agents'].items():
            if aid != 'root' and agent.get('active', True):
                self.cli('read', '--agent', aid)
                self.cli('repo', 'view', '--agent', aid)

    def add(self, aid='worker', parent='root'):
        self.cli('agent', 'add', '--id', aid, '--parent', parent, '--task', 'Review module', '--owns', 'src')

    def report(self, aid, round_no):
        name = aid + str(round_no) + '.txt'
        self.write(name, aid + ' round ' + str(round_no) + ': observed code and checked scope')
        extra = []
        if aid == 'root':
            self.write('completion.txt', 'Goal checked item by item; delivery and scoped tests reviewed')
            extra = ['--completion', 'completion.txt']
        self.cli('report', '--agent', aid, '--summary', 'Observed scoped behavior', '--evidence', name,
                 '--next', 'Independent review', '--round', str(round_no), '--source', 'src/code.py', *extra)

    def review(self, aid, target):
        name = aid + '-reviews-' + target + '.txt'
        self.write(name, 'Independent review by ' + aid + ' of ' + target + ': checks and limitations')
        self.cli('review', '--agent', aid, '--target', target, '--verdict', 'accepted', '--evidence', name)

    def test_init_unicode_alias_and_no_reset(self):
        self.cli('init', '--goal', '中文目标', '--next', '下一步', '--level', 'media')
        self.assertEqual(self.state()['level'], 'medium')
        self.assertIn('中文目标', (self.root / '.jspace/CONTROL.md').read_text(encoding='utf-8'))
        self.cli('init', '--goal', 'Replacement', '--next', 'No', '--level', 'low', ok=False)
        self.assertEqual(self.state()['goal'], '中文目标')

    def test_reserved_state_directory_is_case_insensitive_for_all_evidence(self):
        self.init()
        self.cli('read')
        for directory in ('.jspace', '.JSPACE', '.JsPaCe'):
            name = directory + '/proof.txt'
            self.write(name, 'Must not be accepted as external task evidence')
            self.assertIn('outside .jspace', self.cli('note', '--check', 'Internal evidence',
                          '--by', 'Inspect each file', '--evidence', name, ok=False))
            self.assertNotIn(name, CONTROL.inventory(self.root))
        self.assertEqual(self.state()['checkpoints'], [])

    def test_readonly_preserves_canonical_bytes_generation_and_current_view(self):
        self.prepare()
        canonical = self.root / '.jspace/control.json'
        view = self.root / '.jspace/CONTROL.md'
        snapshot = (canonical.read_bytes(), canonical.stat().st_mtime_ns, view.stat().st_mtime_ns)
        for args in [('status',), ('repo', 'check'), ('check', '--stage', 'work')]:
            self.cli(*args)
            self.assertEqual((canonical.read_bytes(), canonical.stat().st_mtime_ns, view.stat().st_mtime_ns), snapshot)
        view.unlink()
        self.cli('status')
        self.assertEqual(canonical.read_bytes(), snapshot[0])
        self.assertEqual(view.read_bytes(), CONTROL.markdown(self.state()))

    def test_readonly_releases_hash_lock_and_rejects_concurrent_state_change(self):
        from unittest.mock import patch
        self.prepare()
        original = CONTROL.inventory
        def interleave(root):
            self.cli('note', '--next', 'Concurrent writer committed while hashing')
            return original(root)
        with patch.object(CONTROL, 'inventory', side_effect=interleave):
            self.assertEqual(CONTROL.main(['--root', str(self.root), 'check', '--stage', 'work']), 2)
        self.assertEqual(self.state()['next'], 'Concurrent writer committed while hashing')
        self.cli('check', '--stage', 'work')

    def test_repo_branch_schema_reports_missing_or_invalid_marker(self):
        self.prepare()
        original = self.state()
        for missing in (True, False):
            state = json.loads(json.dumps(original))
            if missing:
                del state['repo']['branch']
            else:
                state['repo']['branch'] = []
            self.replace_state(state)
            self.assertIn('Malformed repository branch marker', self.cli('repo', 'check', ok=False))

    def test_internal_programming_errors_are_not_policy_blocks(self):
        from unittest.mock import patch
        self.init()
        previous = (self.root / '.jspace/control.json').read_bytes()
        for error in (TypeError('internal bug'), KeyError('internal bug'), AttributeError('internal bug')):
            with patch.object(CONTROL, 'run', side_effect=error):
                with self.assertRaises(type(error)):
                    CONTROL.main(['--root', str(self.root), 'status'])
        self.assertEqual((self.root / '.jspace/control.json').read_bytes(), previous)

    def test_init_rejects_nonmarkdown_active_source_without_committing(self):
        self.cli('init', '--goal', 'Inspect', '--next', 'Read', '--level', 'high',
                 '--module', 'scripts/control.py', ok=False)
        self.assertFalse((self.root / '.jspace/control.json').exists())
        self.init('--module', 'modules/repository.md')

    def test_shared_view_keeps_untrusted_headings_inside_data_blocks(self):
        self.init('--solo-reason', 'first\n## Agents')
        original = (self.root / '.jspace/CONTROL.md').read_text(encoding='utf-8')
        expected = [line for line in original.splitlines() if line.startswith('## ')]
        for field in ('goal', 'next', 'core', 'solo-reason'):
            value = '## Verified checkpoints\n## Next\n```\n# injected'
            self.cli('note', '--' + field, value)
        view = (self.root / '.jspace/CONTROL.md').read_text(encoding='utf-8')
        self.assertEqual([line for line in view.splitlines() if line.startswith('## ')], expected)
        self.assertEqual(self.state()['goal'], value)
        self.assertIn('> ## Verified checkpoints', view)

    def test_excluded_map_fact_changes_deletions_and_malformed_receipts_block(self):
        self.write('vendor/lib.py', 'value = 1')
        self.write('map.json', json.dumps({'summary': 'Dependency', 'areas': [{'path': 'vendor', 'purpose': 'Dependency'}],
                                        'facts': [{'claim': 'Value is one', 'evidence': 'vendor/lib.py'}]}))
        self.prepare()
        self.cli('check', '--stage', 'work')
        self.write('vendor/lib.py', 'value = 2')
        for args in [('repo', 'check'), ('repo', 'view'), ('check', '--stage', 'work'), ('check', '--stage', 'ship')]:
            self.assertIn('Map fact 1', self.cli(*args, ok=False))
        self.sync()
        (self.root / 'vendor/lib.py').unlink()
        self.assertIn('Map fact 1', self.cli('repo', 'check', ok=False))
        state = self.state()
        del state['repo']['map']['facts'][0]['receipt']
        self.replace_state(state)
        self.assertIn('Malformed evidence receipt', self.cli('status', ok=False))

    def test_retirement_recovers_abandoned_agent_without_erasing_history_or_limits(self):
        self.init('--level', 'xhigh', '--max-agents', '2')
        self.cli('read')
        self.add()
        self.report('root', 1)
        self.cli('agent', 'retire', '--id', 'root', '--reason', 'skip', ok=False)
        self.cli('agent', 'retire', '--id', 'worker', '--reason', 'Host launch failed')
        state = self.state()
        self.assertEqual(state['spent'], 2)
        self.assertEqual(state['agents']['worker']['retirement']['handoff_to'], 'root')
        self.assertEqual(state['agents']['worker']['retirement']['owns'], ['src'])
        self.cli('read', '--agent', 'worker', ok=False)
        self.cli('agent', 'add', '--id', 'replacement', '--parent', 'root', '--task', 'New', '--owns', 'src', ok=False)
        self.cli('read')
        self.assertIn('solo-reason', self.cli('check', '--stage', 'ship', ok=False))
        self.cli('note', '--solo-reason', 'Host cannot launch agents; root takes unfinished scope')
        self.assertIn('retirement changed integration scope', self.cli('check', '--stage', 'ship', ok=False))
        self.report('root', 1)
        self.cli('check', '--stage', 'ship')
        self.assertIn('Host launch failed', self.cli('read'))

    def test_retirement_requires_active_child_cleanup_and_successor(self):
        self.init()
        self.add()
        self.add('child', 'worker')
        self.cli('agent', 'retire', '--id', 'worker', '--reason', 'Rescope', ok=False)
        self.cli('agent', 'retire', '--id', 'child', '--reason', 'Rescope', '--handoff-to', 'missing', ok=False)
        self.cli('agent', 'retire', '--id', 'child', '--reason', 'Rescope')
        self.cli('agent', 'retire', '--id', 'worker', '--reason', 'Rescope')
        self.assertFalse(self.state()['agents']['child']['active'])

    def test_every_active_delegate_must_view_final_map(self):
        self.prepare()
        self.add()
        self.cli('read', '--agent', 'worker')
        self.report('worker', 1)
        self.report('worker', 2)
        self.review('root', 'worker')
        self.report('root', 1)
        self.sync()
        self.write('new-scope.txt', 'Additional integration fact')
        self.cli('repo', 'sync', '--map', 'map.json')
        self.cli('repo', 'view')
        self.cli('read', '--agent', 'worker')
        self.assertIn('worker must run repo view', self.cli('check', '--stage', 'ship', ok=False))
        self.cli('repo', 'view', '--agent', 'worker')
        self.cli('check', '--stage', 'ship')

    def test_goal_change_requires_delegate_reconsideration_and_fresh_review(self):
        self.init()
        self.cli('read')
        self.add()
        self.cli('read', '--agent', 'worker')
        self.report('worker', 1)
        self.report('worker', 2)
        self.review('root', 'worker')
        self.report('root', 1)
        self.cli('note', '--goal', 'Changed scope')
        self.cli('read', '--agent', 'worker')
        self.report('root', 1)
        self.assertIn('worker task contract changed', self.cli('check', '--stage', 'ship', ok=False))
        self.cli('review', '--agent', 'root', '--target', 'worker', '--verdict', 'accepted',
                 '--evidence', 'root-reviews-worker.txt', ok=False)
        self.report('worker', 1)
        self.cli('note', '--core', 'New boundary')
        self.cli('read', '--agent', 'worker')
        self.cli('report', '--agent', 'worker', '--summary', 'Old cycle', '--next', 'Review', '--round', '2',
                 '--evidence', 'worker2.txt', '--source', 'src/code.py', ok=False)
        self.report('worker', 1)
        self.report('worker', 2)
        self.review('root', 'worker')
        self.report('root', 1)
        self.cli('check', '--stage', 'ship')

    def test_work_requires_real_reads_map_and_view(self):
        self.init('--module', 'modules/repository.md')
        self.cli('check', '--stage', 'work', ok=False)
        source = (SCRIPT.parents[1] / 'SKILL.md').read_text(encoding='utf-8')
        output = self.cli('read')
        self.assertIn(source, output)
        self.cli('check', '--stage', 'work', ok=False)
        self.cli('repo', 'sync', '--map', 'map.json')
        self.cli('check', '--stage', 'work', ok=False)
        self.cli('repo', 'view')
        self.cli('check', '--stage', 'work')

    def test_route_preserves_state_and_requires_fresh_agent_reads(self):
        self.init()
        self.cli('read')
        self.add()
        self.cli('read', '--agent', 'worker')
        self.cli('note', '--next', 'Inspect trust boundary')
        self.cli('route', '--level', 'xhigh', '--module', 'modules/cyber.md',
                 '--reason', 'A trust boundary needs independent review')
        state = self.state()
        self.assertEqual(state['next'], 'Inspect trust boundary')
        self.assertEqual(state['level'], 'xhigh')
        self.assertIn('modules/cyber.md', state['modules'])
        self.assertTrue(all(a['broadcast'] for a in state['agents'].values()))
        self.assertIn('--- BEGIN modules/cyber.md', self.cli('read', '--agent', 'worker'))
        self.cli('route', '--level', 'low', '--reason', 'Skip review', ok=False)
        self.assertEqual(self.state()['level'], 'xhigh')

    def test_repo_content_change_and_view_after_sync(self):
        self.prepare()
        self.write('src/code.py', 'value = 2\n')
        self.cli('repo', 'check', ok=False)
        self.cli('check', '--stage', 'work', ok=False)
        self.cli('repo', 'sync', '--map', 'map.json')
        self.cli('check', '--stage', 'work', ok=False)
        self.cli('repo', 'view')
        self.cli('check', '--stage', 'work')

    def test_branch_switch_invalidates_repo(self):
        self.write('.git/HEAD', 'ref: refs/heads/main\n')
        self.prepare()
        self.write('.git/HEAD', 'ref: refs/heads/other\n')
        self.cli('repo', 'check', ok=False)

    def test_dependencies_and_control_state_excluded(self):
        self.prepare()
        self.write('node_modules/lib/index.js', 'dependency')
        self.write('.git/config', 'git metadata')
        self.cli('note', '--next', 'Continue')
        self.cli('repo', 'check')

    def test_pulse_count_time_and_critical_events(self):
        self.prepare()
        for _ in range(4):
            self.assertNotIn('--- BEGIN SKILL.md', self.cli('pulse', '--event', 'tool'))
        self.assertIn('--- BEGIN SKILL.md', self.cli('pulse', '--event', 'tool'))
        state = self.state()
        state['agents']['root']['last_pulse'] = time.time() - 601
        self.replace_state(state)
        self.assertIn('--- BEGIN SKILL.md', self.cli('pulse', '--event', 'tool'))
        for event in ('checkpoint', 'handoff', 'failure', 'resume', 'compact'):
            self.assertIn('--- BEGIN SKILL.md', self.cli('pulse', '--event', event))

    def test_expired_and_modified_source_receipts_fail(self):
        self.prepare()
        state = self.state()
        state['agents']['root']['reads']['SKILL.md']['time'] = time.time() - 1801
        self.replace_state(state)
        self.cli('check', '--stage', 'work', ok=False)
        self.cli('pulse', '--event', 'tool')
        self.cli('check', '--stage', 'work')
        state = self.state()
        state['agents']['root']['reads']['SKILL.md']['sha256'] = 'wrong'
        self.replace_state(state)
        self.cli('check', '--stage', 'work', ok=False)

    def test_agent_reads_and_broadcast_are_independent(self):
        self.prepare()
        self.add()
        self.cli('repo', 'view', '--agent', 'worker')
        self.cli('check', '--stage', 'work', '--agent', 'worker', ok=False)
        self.cli('read', '--agent', 'worker')
        self.cli('check', '--stage', 'work', '--agent', 'worker')
        self.cli('pulse', '--event', 'handoff')
        self.cli('check', '--stage', 'work', '--agent', 'worker', ok=False)
        self.cli('read', 'SKILL.md', '--agent', 'worker')
        self.cli('check', '--stage', 'work', '--agent', 'worker', ok=False)
        self.cli('pulse', '--event', 'resume', '--agent', 'worker')
        self.cli('check', '--stage', 'work', '--agent', 'worker')

    def test_bounded_recursion_and_credits(self):
        self.init('--max-depth', '1', '--budget', '2')
        self.add()
        self.cli('agent', 'add', '--id', 'nested', '--parent', 'worker', '--task', 'Nested', '--owns', 'src', ok=False)
        self.add('other')
        self.cli('agent', 'add', '--id', 'exhausted', '--parent', 'root', '--task', 'Too much', '--owns', 'src', ok=False)
        self.assertEqual(self.state()['spent'], 2)

    def test_round_two_and_independent_review_shipping(self):
        self.prepare()
        self.assertIn('cannot launch agents', self.cli('status'))
        self.add()
        self.cli('read', '--agent', 'worker')
        self.report('root', 1)
        self.report('worker', 1)
        self.report('root', 2)
        self.report('worker', 2)
        self.review('root', 'worker')
        self.review('worker', 'root')
        self.sync()
        self.cli('check', '--stage', 'ship')
        self.write('worker2.txt', 'changed after acceptance')
        self.sync()
        self.cli('check', '--stage', 'ship', ok=False)

    def test_report_reset_invalidates_acceptance(self):
        self.prepare()
        self.add()
        self.cli('read', '--agent', 'worker')
        self.report('worker', 1)
        self.review('root', 'worker')
        self.report('worker', 2)
        self.assertIsNone(self.state()['agents']['worker']['reports'][-1]['review'])
        self.cli('review', '--agent', 'worker', '--target', 'worker', '--verdict', 'accepted', '--evidence', 'worker1.txt', ok=False)
        self.cli('report', '--agent', 'root', '--summary', 'No first round', '--evidence', 'worker1.txt',
                 '--next', 'Review', '--round', '2', ok=False)

    def test_security_evidence_and_distinct_fix_assessment(self):
        self.prepare()
        self.write('repro.txt', 'Actual local reproduction and input')
        self.write('negative.txt', 'Negative control does not reproduce')
        self.cli('security', 'add', '--id', 'F1', '--claim', 'Boundary failure', '--scope', 'local fixture',
                 '--repro', 'repro.txt', '--expected', 'Reject input', '--observed', 'Accepted input', '--negative', 'negative.txt')
        self.assertEqual(self.state()['findings']['F1']['status'], 'candidate')
        self.cli('security', 'resolve', '--id', 'F1', '--status', 'confirmed', '--evidence', 'missing.txt', ok=False)
        self.cli('security', 'resolve', '--id', 'F1', '--status', 'fixed', '--evidence', 'repro.txt', ok=False)
        self.write('assessment.txt', 'Independent assessment of reproduction and scope')
        self.cli('security', 'resolve', '--id', 'F1', '--status', 'fixed', '--evidence', 'assessment.txt', ok=False)
        self.cli('security', 'resolve', '--id', 'F1', '--status', 'confirmed', '--evidence', 'assessment.txt')
        self.write('fix.txt', 'Original reproduction now fails and controls pass after patch')
        self.cli('security', 'resolve', '--id', 'F1', '--status', 'fixed', '--evidence', 'fix.txt')
        self.assertEqual(len(self.state()['findings']['F1']['history']), 2)
        self.write('negative.txt', 'Changed negative control')
        self.cli('security', 'resolve', '--id', 'F1', '--status', 'rejected', '--evidence', 'assessment.txt', ok=False)

    def test_nonrepository_high_solo_can_ship_with_completion(self):
        self.init()
        self.cli('read')
        self.cli('check', '--stage', 'work')
        self.report('root', 1)
        self.cli('check', '--stage', 'ship')
        self.cli('note', '--goal', 'Changed delivery goal')
        self.cli('check', '--stage', 'ship', ok=False)
        self.report('root', 1)
        self.cli('check', '--stage', 'ship')
        self.write('completion.txt', 'Changed after completion attestation')
        self.cli('check', '--stage', 'ship', ok=False)

    def test_xhigh_requires_delegation_or_explicit_limitation(self):
        self.cli('init', '--goal', 'Review argument', '--next', 'Read premises', '--level', 'xhigh')
        self.cli('read')
        self.report('root', 1)
        self.cli('check', '--stage', 'ship', ok=False)
        self.cli('note', '--solo-reason', 'Host has no agent launch tool; independent review is unavailable')
        self.cli('check', '--stage', 'ship')

    def test_source_change_invalidates_accepted_report(self):
        self.prepare()
        self.add()
        self.cli('read', '--agent', 'worker')
        self.report('worker', 1)
        self.report('worker', 2)
        self.review('root', 'worker')
        self.report('root', 1)
        self.sync()
        self.cli('check', '--stage', 'ship')
        self.write('src/code.py', 'value = 3\n')
        self.sync()
        self.cli('check', '--stage', 'ship', ok=False)
        self.cli('review', '--agent', 'root', '--target', 'worker', '--verdict', 'accepted',
                 '--evidence', 'root-reviews-worker.txt', ok=False)

    def test_confirmed_audit_can_ship_with_explicit_disposition(self):
        self.prepare()
        self.write('repro.txt', 'Local reproduction fails the contract')
        self.write('negative.txt', 'Negative control passes')
        self.write('assessment.txt', 'Confirmed with bounded scope and documented impact')
        self.cli('security', 'add', '--id', 'Audit1', '--claim', 'Contract failure', '--scope', 'Local authorized fixture',
                 '--repro', 'repro.txt', '--expected', 'Rejected', '--observed', 'Accepted', '--negative', 'negative.txt')
        self.cli('security', 'resolve', '--id', 'Audit1', '--status', 'confirmed', '--evidence', 'assessment.txt')
        self.report('root', 1)
        self.sync()
        self.cli('check', '--stage', 'ship', ok=False)
        self.cli('security', 'resolve', '--id', 'Audit1', '--status', 'confirmed', '--disposition', 'report',
                 '--evidence', 'assessment.txt')
        self.cli('check', '--stage', 'ship')

    def test_shared_core_checkpoint_and_question_lifecycle(self):
        self.init()
        self.cli('read')
        for item in ('Old anchor', 'Current contract', 'Current invariant'):
            self.cli('note', '--core', item)
        self.assertEqual(self.state()['core'], ['Current contract', 'Current invariant'])
        self.assertEqual(self.state()['parked_core'], ['Old anchor'])
        self.assertIn('Old anchor', (self.root / '.jspace/CONTROL.md').read_text(encoding='utf-8'))
        self.cli('note', '--core', 'Current contract')
        self.assertEqual(self.state()['core'], ['Current invariant', 'Current contract'])
        self.cli('note', '--open', 'Does the boundary hold?', '--settled-by', 'A local negative-control test')
        self.assertIn('Q1', self.state()['questions'])
        self.cli('note', '--close', 'Q1', ok=False)
        self.write('checkpoint.txt', 'Local control and boundary test passed')
        self.cli('note', '--check', 'Boundary holds', '--by', 'Fixture covering valid and malformed input',
                 '--evidence', 'checkpoint.txt', '--close', 'Q1')
        self.assertTrue(self.state()['questions']['Q1']['closed'])
        self.assertEqual(self.state()['questions']['Q1']['checkpoint'], 1)
        self.assertIn('Current invariant', self.cli('pulse', '--event', 'tool'))

    def test_closed_question_evidence_is_revalidated_and_can_be_reopened(self):
        self.init()
        self.cli('read')
        self.write('closure.txt', 'Original observation establishes the boundary')
        self.cli('note', '--open', 'Boundary behavior?', '--settled-by', 'Run local boundary fixture')
        self.cli('note', '--check', 'Boundary holds', '--by', 'Valid and invalid fixture inputs',
                 '--evidence', 'closure.txt', '--close', 'Q1')
        self.report('root', 1)
        self.cli('check', '--stage', 'work')
        self.cli('check', '--stage', 'ship')
        self.write('closure.txt', 'New observation changes the earlier result')
        self.cli('check', '--stage', 'work', ok=False)
        self.cli('check', '--stage', 'ship', ok=False)
        self.cli('note', '--reopen', 'Q1')
        self.cli('check', '--stage', 'work')
        self.cli('check', '--stage', 'ship', ok=False)
        self.cli('note', '--check', 'Rechecked boundary under updated conditions', '--by', 'Updated fixture and negative control',
                 '--evidence', 'closure.txt', '--close', 'Q1')
        self.cli('check', '--stage', 'ship')
        question = self.state()['questions']['Q1']
        self.assertEqual(question['closure_history'], [1])
        self.assertEqual(question['checkpoint'], 2)
        self.assertEqual(len(self.state()['checkpoints']), 2)

    def test_fixed_finding_revalidates_its_confirmed_assessment(self):
        self.init()
        self.cli('read')
        for name, content in [('repro.txt', 'Reproduction result'), ('negative.txt', 'Control result'),
                              ('confirmed.txt', 'Independent confirmation'), ('fixed.txt', 'Regression after patch')]:
            self.write(name, content)
        self.cli('security', 'add', '--id', 'F', '--claim', 'Boundary failure', '--scope', 'Local fixture',
                 '--repro', 'repro.txt', '--expected', 'Reject', '--observed', 'Accept', '--negative', 'negative.txt')
        self.cli('security', 'resolve', '--id', 'F', '--status', 'confirmed', '--evidence', 'confirmed.txt')
        self.write('confirmed.txt', 'Changed assessment before the fix')
        self.cli('security', 'resolve', '--id', 'F', '--status', 'fixed', '--evidence', 'fixed.txt', ok=False)
        self.cli('security', 'resolve', '--id', 'F', '--status', 'confirmed', '--evidence', 'confirmed.txt')
        self.cli('security', 'resolve', '--id', 'F', '--status', 'fixed', '--evidence', 'fixed.txt')
        self.report('root', 1)
        self.cli('check', '--stage', 'ship')
        self.write('confirmed.txt', 'Changed assessment after the fix')
        self.cli('check', '--stage', 'ship', ok=False)

    def test_standalone_checkpoint_staleness_and_supersession(self):
        self.init()
        self.cli('read')
        self.write('proof.txt', 'Observed boundary behavior')
        self.cli('note', '--check', 'Boundary holds', '--by', 'Local valid and invalid cases', '--evidence', 'proof.txt')
        self.report('root', 1)
        self.cli('check', '--stage', 'ship')
        self.write('proof.txt', 'Observation has changed')
        self.cli('check', '--stage', 'work', ok=False)
        self.cli('check', '--stage', 'ship', ok=False)
        self.write('replacement.txt', 'Rechecked boundary with corrected fixture')
        self.cli('note', '--check', 'Corrected boundary supported', '--by', 'Corrected fixture and control',
                 '--evidence', 'replacement.txt', '--supersede', '1')
        self.cli('check', '--stage', 'work')
        self.cli('check', '--stage', 'ship')
        self.assertEqual(self.state()['checkpoints'][0]['superseded_by'], 2)
        self.assertFalse(self.state()['checkpoints'][0]['active'])

    def test_child_read_receives_latest_shared_contract_and_checkpoint(self):
        self.init()
        self.add()
        self.write('proof.txt', 'Checked shared input boundary')
        self.cli('note', '--goal', 'Changed shared goal', '--check', 'Boundary checked',
                 '--by', 'Input fixture and negative control', '--evidence', 'proof.txt')
        output = self.cli('read', '--agent', 'worker')
        self.assertIn('Goal: Changed shared goal', output)
        self.assertIn('Boundary checked [evidence: proof.txt]', output)
        self.assertFalse(self.state()['agents']['worker']['broadcast'])

    def test_second_report_preserves_first_round_evidence(self):
        self.init()
        self.add()
        self.cli('read', '--agent', 'worker')
        self.report('worker', 1)
        self.write('worker1.txt', 'Overwritten first observation')
        self.cli('report', '--agent', 'worker', '--summary', 'Second pass', '--evidence', 'worker1.txt',
                 '--next', 'Review', '--round', '2', ok=False)
        self.write('worker2.txt', 'Second observation')
        self.cli('report', '--agent', 'worker', '--summary', 'Second pass', '--evidence', 'worker2.txt',
                 '--next', 'Review', '--round', '2', ok=False)

    def test_tuning_preserves_work_and_invalidates_source_receipts(self):
        self.init()
        self.cli('read')
        self.cli('note', '--next', 'Continue bounded analysis')
        self.cli('tune', '--pulse-count', '2', '--pulse-seconds', '240', '--reason', 'Two observed context drifts')
        state = self.state()
        self.assertEqual(state['next'], 'Continue bounded analysis')
        self.assertEqual(state['config']['pulse_count'], 2)
        self.assertEqual(state['tuning'][0]['previous']['pulse_count'], 5)
        self.cli('check', '--stage', 'work', ok=False)
        self.cli('read')
        self.cli('check', '--stage', 'work')
        self.cli('tune', '--pulse-count', '0', '--reason', 'Invalid interval', ok=False)
        self.assertEqual(self.state()['config']['pulse_count'], 2)

    def test_root_completion_is_bound_to_core_and_route(self):
        self.init()
        self.cli('read')
        self.report('root', 1)
        self.cli('check', '--stage', 'ship')
        self.cli('note', '--core', 'Public contract: keep response shape')
        self.cli('check', '--stage', 'ship', ok=False)
        self.report('root', 1)
        self.cli('check', '--stage', 'ship')
        self.cli('route', '--module', 'modules/epistemics.md', '--reason', 'Revisit implicit assumptions')
        self.cli('read')
        self.cli('check', '--stage', 'ship', ok=False)
        self.report('root', 1)
        self.cli('check', '--stage', 'ship')

    def test_reparse_detection_without_path_is_junction(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        junction = self.root / 'junction'
        self.write('junction/outside.txt', 'This must not enter inventory')
        original_lstat = Path.lstat

        def lstat(path):
            info = original_lstat(path)
            if path == junction:
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
            return info

        with patch.object(Path, 'lstat', lstat):
            self.assertTrue(CONTROL.linked(junction))
            with self.assertRaises(CONTROL.ControlError):
                CONTROL.safe_path(self.root, 'junction/outside.txt')
            self.assertNotIn('junction/outside.txt', CONTROL.inventory(self.root))

    def test_inventory_hashes_large_files_in_bounded_chunks(self):
        from unittest.mock import patch
        path = self.root / 'large.bin'
        expected = CONTROL.hashlib.sha256()
        block = b'0123456789abcdef' * 65536
        with path.open('wb') as handle:
            for _ in range(4):
                handle.write(block)
                expected.update(block)
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('Whole-file reads are forbidden for inventory')):
            inventory = CONTROL.inventory(self.root)
        self.assertEqual(inventory['large.bin'], expected.hexdigest())

    def test_host_bridge_can_ship_team_after_checkpoint_injection(self):
        self.prepare()
        self.add()
        self.cli('read', '--agent', 'worker')
        self.report('worker', 1)
        self.report('worker', 2)
        self.review('root', 'worker')
        self.report('root', 1)
        self.sync()
        bridge = SCRIPT.with_name('host_bridge.py')
        for _ in range(2):
            result = subprocess.run([sys.executable, str(bridge), '--root', str(self.root)],
                                    input='{"event":"before_ship","agent":"root"}', capture_output=True,
                                    encoding='utf-8', timeout=25)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(json.loads(result.stdout)['allow'])
            self.assertFalse(self.state()['agents']['worker']['broadcast'])
        self.cli('note', '--goal', 'Changed contract')
        self.assertTrue(self.state()['agents']['worker']['broadcast'])

    def test_traversal_absolute_empty_and_malformed_json_fail_closed(self):
        self.init()
        initial = (self.root / '.jspace/control.json').read_bytes()
        self.cli('read', '../README.md', ok=False)
        self.cli('read', str(SCRIPT), ok=False)
        self.write('invalid.json', '[]')
        self.cli('repo', 'sync', '--map', 'invalid.json', ok=False)
        self.assertEqual(initial, (self.root / '.jspace/control.json').read_bytes())
        for value in ('[]', '{broken', '{"schema":1,"goal":[]}'):
            (self.root / '.jspace/control.json').write_text(value, encoding='utf-8')
            self.cli('status', ok=False)
            self.assertEqual(value, (self.root / '.jspace/control.json').read_text(encoding='utf-8'))

    def test_symlink_evidence_and_state_rejected_inventory_ignores(self):
        self.prepare()
        link = self.root / 'linked.py'
        try:
            link.symlink_to(self.root / 'src/code.py')
        except OSError:
            self.skipTest('Creating symlinks is unavailable on this host.')
        self.cli('repo', 'check')
        self.cli('report', '--agent', 'root', '--summary', 'Link', '--evidence', 'linked.py',
                 '--next', 'Review', '--round', '1', ok=False)
        view = self.root / '.jspace/CONTROL.md'
        view.unlink()
        view.symlink_to(self.root / 'src/code.py')
        self.cli('status', ok=False)
        self.assertEqual((self.root / 'src/code.py').read_text(), 'value = 1\n')

    def test_concurrent_writers_preserve_all_agent_registrations(self):
        self.init('--max-agents', '20')
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i: self.add('agent' + str(i)), range(12)))
        state = self.state()
        self.assertEqual(len(state['agents']), 13)
        self.assertEqual(state['spent'], 12)
        self.assertEqual(state['generation'], 13)

    def test_lock_released_after_process_crash(self):
        self.init()
        code = ('import importlib.util,sys,time; from pathlib import Path; '
                's=importlib.util.spec_from_file_location("control",sys.argv[1]); '
                'm=importlib.util.module_from_spec(s); s.loader.exec_module(m); '
                'lock=m.locked(Path(sys.argv[2])); lock.__enter__(); print("locked",flush=True); time.sleep(60)')
        process = subprocess.Popen([sys.executable, '-c', code, str(SCRIPT), str(self.root)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), 'locked')
            process.kill()
            process.communicate(timeout=5)
            self.cli('status')
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()

    def test_atomic_replace_failure_keeps_canonical_state(self):
        from unittest.mock import patch
        path = self.write('atomic.txt', 'original')
        with patch.object(CONTROL.os, 'replace', side_effect=OSError('injected failure')):
            with self.assertRaises(OSError):
                CONTROL.atomic(path, b'changed')
        self.assertEqual(path.read_text(), 'original')
        self.assertEqual(list(self.root.glob('.control-*')), [])


if __name__ == '__main__':
    unittest.main()
