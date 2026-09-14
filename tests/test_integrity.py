"""Malformed-package diagnostics, reverse routes, and durable advisory writes."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SKILL = Path(__file__).resolve().parents[1] / 'j-space'


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='skill installed path ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'j-space'
        shutil.copytree(SKILL, self.root, ignore=shutil.ignore_patterns('__pycache__'))

    def verify(self):
        result = subprocess.run([sys.executable, str(self.root / 'scripts/verify_suite.py')],
                                capture_output=True, encoding='utf-8', timeout=30)
        self.assertNotIn('Traceback', result.stderr)
        return result

    def test_missing_directories_and_invalid_utf8_preserve_findings(self):
        # The copy is inside this test's disposable TemporaryDirectory.
        shutil.rmtree(self.root / 'modules')
        shutil.rmtree(self.root / 'references')
        (self.root / 'broken.md').write_bytes(b'\xff\xfeinvalid')
        result = self.verify()
        self.assertEqual(result.returncode, 1)
        self.assertIn('cannot list resource directory', result.stdout)
        self.assertIn('cannot read UTF-8 source', result.stdout)
        self.assertIn('modules/introspection.md', result.stdout.replace('\\', '/'))

    def test_reverse_and_unlinked_routes_are_detected(self):
        path = self.root / 'modules/directed-focus.md'
        text = path.read_text(encoding='utf-8')
        path.write_text(text.replace('[Entry](../SKILL.md)', '`../SKILL.md`'), encoding='utf-8')
        result = self.verify()
        self.assertEqual(result.returncode, 1)
        self.assertIn('Hand-off must link back', result.stdout)
        self.assertIn('must use Markdown links', result.stdout)

    def test_installed_skill_with_spaces_and_license_files_verifies(self):
        for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md'):
            shutil.copyfile(SKILL.parent / name, self.root / name)
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_advisory_write_syncs_before_replace_and_keeps_lf(self):
        spec = importlib.util.spec_from_file_location('advisory_durability', SKILL / 'scripts/jspace.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        path = Path(self.temp.name) / 'ledger.txt'
        order = []
        real_fsync, real_replace = module.os.fsync, module.os.replace
        def synced(fd):
            order.append('fsync')
            return real_fsync(fd)
        def replaced(source, target):
            order.append('replace')
            return real_replace(source, target)
        with patch.object(module, 'LEDGER_DIR', self.temp.name), \
             patch.object(module.os, 'fsync', side_effect=synced), \
             patch.object(module.os, 'replace', side_effect=replaced):
            self.assertIsNone(module.atomic_write_text(str(path), 'alpha\nbeta\n'))
        self.assertEqual(order, ['fsync', 'replace'])
        self.assertEqual(path.read_bytes(), b'alpha\nbeta\n')


if __name__ == '__main__':
    unittest.main()
