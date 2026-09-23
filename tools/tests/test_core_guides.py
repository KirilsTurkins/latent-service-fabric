"""Focused guide/source regressions; these do not execute LSF or certify prose."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
GUIDES = {
    'evaluate-boundary': ['docs/start/index.md'],
    'install-auth-readiness': ['docs/start/first-node.md', 'docs/installation.md'],
    'contributor-checks': ['docs/how-to/operate-and-contribute.md'],
    'author-capsule': ['docs/learn/author-your-first-capsule.md'],
    'package-sign-publish': ['docs/learn/author-your-first-capsule.md', 'docs/learn/deliver-and-recover-a-capsule.md'],
    'rollout-uncertain-recovery': ['docs/learn/deliver-and-recover-a-capsule.md', 'docs/how-to/operate-and-contribute.md'],
}
NEW_GUIDES = ('docs/start/index.md', 'docs/start/first-node.md',
              'docs/learn/author-your-first-capsule.md', 'docs/how-to/operate-and-contribute.md',
              'docs/development/core-guide-validation.md')


def fences(text):
    """Only the documented, closed backtick fences in these maintained guides."""
    lines = text.splitlines(keepends=True)
    result = []
    language = None
    content = []
    for line in lines:
        if line.startswith('```'):
            if language is None:
                language = line[3:].strip()
                content = []
            else:
                if line.strip() != '```':
                    raise AssertionError('nonclosing guide fence')
                result.append((language, ''.join(content)))
                language = None
        elif language is not None:
            content.append(line)
    if language is not None:
        raise AssertionError('unclosed guide fence')
    return result


class CoreGuides(unittest.TestCase):
    def test_six_existing_outcomes_reference_guides_and_validation_owner(self):
        rows = json.loads((ROOT / 'website/content/coverage.json').read_text(encoding='utf-8'))['rows']
        selected = {row['id']: row for row in rows if row['guideIssue'] == 357}
        self.assertEqual(set(selected), set(GUIDES))
        for identifier, paths in GUIDES.items():
            row = selected[identifier]
            entries = {page['path']: page['role'] for page in row['pages']}
            self.assertEqual(len(entries), len(row['pages']))
            for path in paths:
                self.assertEqual(entries[path], 'guide', path)
            self.assertIn('docs/development/core-guide-validation.md', row['sourceRefs'])
            if row['review']['status'] == 'pending':
                self.assertIsNone(row['review']['reviewedCommit'])
                self.assertEqual(row['review']['criteria'], [])
        evidence = selected['install-auth-readiness']['evidence']
        self.assertTrue(any(item['path'] == 'tools/run_first_node_guide.py'
                            and item['kind'] == 'test-source'
                            and item['status'] == 'available-not-run' for item in evidence))

    def test_real_guest_region_is_referenced_without_copying_implementation(self):
        guide = (ROOT / 'docs/learn/author-your-first-capsule.md').read_text(encoding='utf-8')
        self.assertEqual(guide.count('<!-- lsf-example: guest/rust-echo echo -->'), 1)
        self.assertNotIn('impl Guest for EchoCapsule', guide)
        self.assertIn('examples/guides/rust-echo/example.json', guide)

    def test_learning_sequence_links_are_present_and_bounded(self):
        first = (ROOT / 'docs/start/first-node.md').read_text(encoding='utf-8')
        self.assertIn('../learn/author-your-first-capsule.md', first)
        self.assertIn('../learn/deliver-and-recover-a-capsule.md', first)
        for name in NEW_GUIDES:
            text = (ROOT / name).read_text(encoding='utf-8')
            self.assertLess(len(text.encode()), 16384)
            self.assertEqual(len(re.findall(r'^# ', text, re.M)), 1, name)
            self.assertNotRegex(text, r'(?m)^(?:<<<<<<< |=======|>>>>>>> )')
            fences(text)

    @unittest.skipUnless(shutil.which('bash'), 'Bash command syntax requires Bash')
    def test_published_shell_blocks_parse_without_executing_commands(self):
        checked = 0
        for name in NEW_GUIDES:
            for language, source in fences((ROOT / name).read_text(encoding='utf-8')):
                if language != 'bash':
                    continue
                result = subprocess.run(['bash', '-n'], input=source.encode(),
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
                self.assertEqual(result.returncode, 0, name)
                checked += 1
        self.assertGreaterEqual(checked, 8)

    def test_published_receipt_reader_accepts_only_complete_success(self):
        text = (ROOT / 'docs/development/core-guide-validation.md').read_text(encoding='utf-8')
        match = re.search(r"<<'PY'\n(.*?)\nPY", text, re.S)
        self.assertIsNotNone(match)
        script = match[1]
        ast.parse(script)
        complete = dict(schemaVersion='latent.first-node-guide.v1', passed=True,
                        successfulInvocations=2, declaredErrors=1,
                        retainedDeploymentInvokedAfterRestart=True, temporaryOutputsRemoved=True,
                        shutdowns=[dict(clean=True, reaped=True), dict(clean=True, reaped=True)])
        candidates = [(complete, 0)]
        for field, value in [('schemaVersion', 'other'), ('passed', False),
                             ('successfulInvocations', 0), ('declaredErrors', 0),
                             ('retainedDeploymentInvokedAfterRestart', False),
                             ('temporaryOutputsRemoved', False), ('shutdowns', []),
                             ('shutdowns', [dict(clean=True, reaped=False)] * 2)]:
            candidates.append(({**complete, field: value}, 1))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'receipt.json'
            for candidate, expected in candidates:
                path.write_text(json.dumps(candidate))
                result = subprocess.run([sys.executable, '-S', '-', str(path)], input=script.encode(),
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
                self.assertEqual(result.returncode, expected)
            path.write_bytes(b' ' * 65537)
            result = subprocess.run([sys.executable, '-S', '-', str(path)], input=script.encode(),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
            self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
