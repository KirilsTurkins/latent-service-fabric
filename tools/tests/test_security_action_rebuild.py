"""Adversarial controls for exact current action rebuild evidence."""
import copy
import json
import unittest

from tools import security_setup_go
from tools.security_action_rebuild import verify_rebuild
from tools.security_common import ROOT, SecurityError, read_file


class ActionRebuildReceiptTests(unittest.TestCase):
    def receipt(self):
        build = json.loads(read_file(ROOT, security_setup_go.MINI_MATERIAL['build'][0]))
        return ROOT, copy.deepcopy(build), security_setup_go.REFERENCE, security_setup_go.RUNTIME

    def test_current_receipt_binds_sources_outputs_and_retained_history(self):
        verify_rebuild(*self.receipt())

    def test_changed_execution_inputs_outputs_and_history_are_rejected(self):
        changes = {
            'unknown-field': lambda b: b.update(future=True),
            'old-schema': lambda b: b.update(schema=1),
            'foreign-revision': lambda b: b.update(publishedRevision='0' * 40),
            'foreign-repository': lambda b: b.update(repository='other/action'),
            'old-history': lambda b: b['previousEvidence'].update(publishedRevision='0' * 40),
            'foreign-history': lambda b: b['previousEvidence'].update(repository='other/action'),
            'queued-job': lambda b: b.update(jobConclusion='queued'),
            'invalid-run': lambda b: b.update(run=True),
            'unobserved-toolchain': lambda b: b['toolchain'].update(node='0.0.0'),
            'missing-log': lambda b: b.update(validationLog={}),
            'invalid-artifact': lambda b: b['artifact'].update(id=False),
            'unhashed-artifact': lambda b: b['artifact'].update(sha256=''),
            'missing-source-control': lambda b: b['validation'].update(sourceControlsPassed=False),
            'missing-xml-control': lambda b: b['validation'].update(xmlRegressionPassed=False),
            'boolean-test-count': lambda b: b['validation'].update(unitTests=True),
            'missing-output': lambda b: b.update(outputs={}),
            'extra-output': lambda b: b['outputs'].update({'../foreign.js': next(iter(b['outputs'].values()))}),
            'changed-output': lambda b: next(iter(b['outputs'].values())).update(sha256='0' * 64),
            'missing-input': lambda b: b.update(sourceFiles={}),
            'changed-input': lambda b: b['sourceFiles']['package.json'].update(sha256='0' * 64),
            'missing-assertion': lambda b: b.update(installedSourceAssertions=[]),
            'foreign-assertion': lambda b: b['installedSourceAssertions'][0].update(sourceCommit='0' * 40),
            'unsupported-promotion': lambda b: b.update(scope='signed SDK qualified'),
        }
        for name, mutate in changes.items():
            with self.subTest(name=name):
                root, build, reference, runtime = self.receipt()
                mutate(build)
                with self.assertRaises(SecurityError):
                    verify_rebuild(root, build, reference, runtime)
