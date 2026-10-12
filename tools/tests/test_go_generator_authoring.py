"""Explicit Go generator approval, immutable source capture and actual containment."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from tools import go_generator_authoring as generators
from tools.application_dependency_store import DependencyError
from tools.build_process import BuildProcessError
from tools.go_capsule_project import create, snapshot, validate
from tools.rust_capsule_project import digest


class GeneratorApprovalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = create(self.root / 'project', 'greeting')
        self.inputs = self.root / 'inputs'
        self.inputs.mkdir()
        (self.inputs / 'value.txt').write_bytes(b'17')
        self.tool = self.root / 'generator'
        self.tool.write_bytes(b'#!/bin/sh\nprintf "package export_examples_greeting_api\\nconst Generated = 17\\n" > /outputs/value.go\n')
        self.tool.chmod(0o700)
        self.candidate = self.project / 'target/request.json'
        self.candidate.parent.mkdir()

    def plan(self, **options):
        return generators.request(self.project, self.candidate, tool=self.tool, arguments=[],
                                  inputs=self.inputs, destination='src/generated', tool_version='fixture-v1', **options)

    def test_request_has_exact_tool_input_source_sdk_and_finite_execution_identity_without_running(self):
        with patch('subprocess.Popen', side_effect=AssertionError('request executed a tool')):
            result = self.plan()
        selected = json.loads(self.candidate.read_bytes())
        self.assertEqual(result['requestDigest'], digest(self.candidate.read_bytes()))
        self.assertEqual(selected['specification']['executableDigest'], digest(self.tool.read_bytes()))
        self.assertEqual(selected['specification']['network'], 'denied')
        self.assertEqual(selected['destination'], 'src/generated')
        self.assertEqual(selected['limits'], {'timeoutSeconds': 60, 'maximumOutputBytes': 1048576})
        self.assertFalse(result['generatorExecution'])
        self.assertTrue(result['approvalRequired'])

    def test_missing_wrong_approval_and_changed_selected_inputs_never_execute(self):
        planned = self.plan()
        before = snapshot(self.project)
        with patch.object(generators.generators, 'execute', side_effect=AssertionError('unapproved tool executed')):
            with self.assertRaisesRegex(DependencyError, 'approval-mismatch'):
                generators.run(self.project, self.candidate, 'sha256:' + '0' * 64)
            (self.inputs / 'value.txt').write_bytes(b'18')
            with self.assertRaisesRegex(DependencyError, 'tool-or-input-drift'):
                generators.run(self.project, self.candidate, planned['requestDigest'])
        self.assertEqual(snapshot(self.project), before)

    def test_changed_application_source_rejects_a_previous_execution_approval(self):
        planned = self.plan()
        (self.project / 'src/main.go').write_bytes((self.project / 'src/main.go').read_bytes() + b'\n// changed\n')
        with patch.object(generators.generators, 'execute', side_effect=AssertionError('stale request executed')):
            with self.assertRaisesRegex(DependencyError, 'source-or-sdk-drift'):
                generators.run(self.project, self.candidate, planned['requestDigest'])

    def test_generator_cannot_overwrite_existing_source_or_sdk_and_cannot_widen_limits(self):
        for destination in ('vendor/lsf/generated', '../outside', 'src/main.go', 'src/nested/generated'):
            with self.subTest(destination=destination), self.assertRaises((DependencyError, ValueError)):
                generators.request(self.project, self.candidate, tool=self.tool, arguments=[], inputs=self.inputs,
                                   destination=destination, tool_version='fixture-v1')
        for options in ({'timeout_seconds': 61}, {'timeout_seconds': float('nan')}, {'maximum_output_bytes': 1048577}):
            with self.subTest(options=options), self.assertRaisesRegex(DependencyError, 'finite-limits'):
                self.plan(**options)


class GeneratorNativeTests(GeneratorApprovalTests):
    @classmethod
    def setUpClass(cls):
        if sys.platform != 'linux' or not shutil.which('bwrap'):
            if os.environ.get('LSF_REQUIRE_COMPILER_ISOLATION') == '1':
                raise RuntimeError('required generator containment host is missing')
            raise unittest.SkipTest('actual Go generator containment requires Linux Bubblewrap')

    def test_actual_approved_generator_captures_sources_and_reuses_them_offline_without_tool(self):
        self.tool.write_bytes(b'#!/usr/bin/python3\n'
            b'import os,pathlib,socket\n'
            b'assert not pathlib.Path("/etc/passwd").exists()\n'
            b'assert not os.environ.get("LSF_GENERATOR_SECRET")\n'
            b'try:\n s=socket.create_connection(("127.0.0.1", 9), timeout=.2)\n'
            b'except OSError: pass\nelse: raise AssertionError("network exposed")\n'
            b'value=pathlib.Path("/inputs/value.txt").read_text()\n'
            b'pathlib.Path("/outputs/value.go").write_text("package export_examples_greeting_api\\nconst Generated = "+value+"\\n")\n')
        self.tool.chmod(0o700)
        sdk = (self.project / 'sdk-lock.json').read_bytes()
        original = snapshot(self.project)
        planned = self.plan()
        with patch.dict(os.environ, {'LSF_GENERATOR_SECRET': 'fixture-not-a-secret'}):
            result = generators.run(self.project, self.candidate, planned['requestDigest'])
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['cleanup'], 'reaped')
        self.assertEqual((self.project / 'sdk-lock.json').read_bytes(), sdk)
        self.assertIn(b'const Generated = 17', (self.project / 'src/generated/value.go').read_bytes())
        after = snapshot(self.project)
        for name, raw in original.items():
            self.assertEqual(after[name], raw)
        validate(after)
        self.tool.unlink()
        (self.inputs / 'value.txt').unlink()
        with patch('subprocess.Popen', side_effect=AssertionError('offline source reuse executed a tool')):
            validate(snapshot(self.project))
        (self.project / 'src/generated/value.go').write_bytes(b'package changed\n')
        with self.assertRaisesRegex(DependencyError, 'generated-inputs-drift'):
            validate(snapshot(self.project))

    def test_actual_cancelled_generator_retains_failed_receipt_and_reaps_descendants_without_adoption(self):
        self.tool.write_bytes(b'#!/bin/sh\nprintf x > /outputs/progress\n'
                             b'while :; do printf x >> /outputs/progress; done &\nwait\n')
        self.tool.chmod(0o700)
        planned = self.plan(timeout_seconds=.25)
        before = snapshot(self.project)
        with self.assertRaisesRegex(BuildProcessError, 'command-deadline'):
            generators.run(self.project, self.candidate, planned['requestDigest'])
        self.assertEqual(snapshot(self.project), before)
        self.assertFalse((self.project / 'src/generated').exists())
        stage = next((self.project / 'target/go-dependency-authoring').glob('generator-*'))
        record = json.loads((stage / 'execution.json').read_bytes())
        outcome = json.loads((stage / 'outcome.json').read_bytes())
        self.assertEqual(record['status'], 'failed')
        self.assertEqual(record['cleanup'], 'reaped')
        self.assertEqual(outcome['status'], 'failed')
        self.assertFalse(outcome['sourceChanged'])
        progress = stage / 'outputs/progress'
        size = progress.stat().st_size
        time.sleep(.1)
        self.assertEqual(progress.stat().st_size, size)


if __name__ == '__main__':
    unittest.main()
