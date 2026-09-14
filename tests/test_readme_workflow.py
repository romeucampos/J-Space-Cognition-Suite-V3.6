"""Execute README command sequences; team IDs simulate mechanics, not model independence."""
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'j-space'


class ReadmeWorkflowTests(unittest.TestCase):
    def test_four_level_tutorial_and_bilingual_command_alignment(self):
        english = (ROOT / 'README.md').read_text(encoding='utf-8')
        chinese = (ROOT / 'README.zh-CN.md').read_text(encoding='utf-8')
        def blocks(text):
            tutorial = text.split('## A short tutorial for all four levels', 1)[-1] if '## A short' in text else text.split('## 四个挡位的简单教程', 1)[1]
            tutorial = tutorial.split('## Shared control', 1)[0].split('## 共享控制', 1)[0]
            return re.findall(r'```text\n(.*?)\n```', tutorial, re.S)
        tutorial = blocks(english)
        self.assertEqual(tutorial, blocks(chinese))
        self.assertEqual(len(tutorial), 4)
        for level in ('low', 'medium', 'high', 'xhigh'):
            self.assertIn('### ' + level, english)
            self.assertIn('### ' + level, chinese)
        with tempfile.TemporaryDirectory(prefix='README task 中文 ') as tmp:
            task = Path(tmp)
            def command(line):
                args = shlex.split(line)
                args[0] = sys.executable
                args = [arg.replace('<skill-root>', str(SKILL)) for arg in args]
                result = subprocess.run(args, cwd=task, capture_output=True, encoding='utf-8', timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            def block(text):
                for line in text.splitlines():
                    command(line)
            def control(args):
                return command('<python-command> <skill-root>/scripts/control.py ' + args)
            # medium: advisory record, real example execution, closure, and text audit.
            block(tutorial[0])
            self.assertEqual(sum([1, 2]), 3)
            command('<python-command> <skill-root>/scripts/jspace.py note --check "Example returns 3" --by "manual inspection of each input and execution of the reported case" --close 1')
            (task / 'answer.md').write_text('The example returns 3 for inputs 1 and 2.', encoding='utf-8')
            command('<python-command> <skill-root>/scripts/jspace.py ship answer.md')
            # Use a separate task root for strict state, as the tutorial instructs.
            task = task / 'strict task'
            task.mkdir()
            (task / 'src').mkdir()
            source = task / 'src/router.py'
            source.write_text('def route():\n    return 1\n', encoding='utf-8')
            (task / 'repo-map.json').write_text(json.dumps({'summary': 'Router fixture',
                'areas': [{'path': 'src', 'purpose': 'Request routing'}],
                'facts': [{'claim': 'route returns an integer', 'evidence': 'src/router.py'}]}), encoding='utf-8')
            shared = english.split('## Shared control', 1)[1].split('## Host integration', 1)[0]
            shared_blocks = re.findall(r'```text\n(.*?)\n```', shared, re.S)
            block(shared_blocks[0])
            block(shared_blocks[1])
            source.write_text('def route():\n    return 2\n', encoding='utf-8')
            observed = subprocess.run([sys.executable, '-c', 'from src.router import route; assert route() == 2; print("route() == 2")'], cwd=task, capture_output=True, encoding='utf-8')
            self.assertEqual(observed.returncode, 0, observed.stderr)
            (task / 'evidence').mkdir()
            (task / 'evidence/root.txt').write_text(observed.stdout, encoding='utf-8')
            (task / 'evidence/completion.txt').write_text('Acceptance: route returns integer 2; subprocess assertion passed.', encoding='utf-8')
            block(tutorial[1])  # high end-to-end
            block(tutorial[2])  # route and bootstrap xhigh
            for round_no in (1, 2):
                name = 'evidence/review-' + str(round_no) + '.txt'
                (task / name).write_text('Fixture inspected in pass ' + str(round_no) + ': ' + observed.stdout, encoding='utf-8')
                control('report --agent reviewer --round %d --summary "Checked fixture" --evidence %s --source src/router.py --next "Review evidence"' % (round_no, name))
            (task / 'evidence/acceptance.txt').write_text('Separate acceptance check: ' + observed.stdout, encoding='utf-8')
            block(tutorial[3])
            final_commands = tutorial[1].splitlines()
            block('\n'.join(final_commands[:3]))  # root report and final sync
            control('read --agent reviewer')
            control('repo view --agent reviewer')
            block('\n'.join(final_commands[3:]))


if __name__ == '__main__':
    unittest.main()
