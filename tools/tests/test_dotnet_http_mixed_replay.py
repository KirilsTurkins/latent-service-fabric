"""Immutable failed guest ancestry and diagnostic-only continuation boundaries."""
import copy
import hashlib
import io
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import dotnet_http_mixed_continuation as continuation
from tools import dotnet_http_mixed_node as node, replay_dotnet_http_mixed as replay
from tools.ci_lane_inventory import workflow_model
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT, digest


class ManagedHttpReplay(unittest.TestCase):
    def actual(self):
        raw = (ROOT/'tools/tests/fixtures/dotnet-http-request-limit-actual.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), '771112cec75409296db09a5fd0a0151bc5b806d4a800534a5ec37c142753369f')
        return json.loads(raw)

    def test_actual_failure_stays_red_under_original_oracle_and_is_only_a_failed_diagnostic(self):
        value = self.actual();revision = value['response']['data']['resolvedRevision']
        budget = {'cpuFuel': 1000000000, 'memoryBytes': 134217728}
        with self.assertRaisesRegex(WorkflowError, 'managed-mixed-default-result'):
            node.checked(value, 8, revision, budget)
        self.assertIsNone(continuation.preserved_limit(value, revision, budget))
        for mutation in ('success', 'error', 'trap-kind', 'revision', 'outbound', 'fuel', 'memory', 'known', 'reaped', 'decoded', 'effect', 'bool'):
            changed = copy.deepcopy(value)
            if mutation == 'success':changed['exitCode'] = 0
            elif mutation == 'error':changed['response']['error']['code'] = 'permission-denied'
            elif mutation == 'trap-kind':changed['response']['error']['details'][1]['fields']['kind'] = 'stack-overflow'
            elif mutation == 'revision':changed['response']['data']['resolvedRevision']['routeGeneration'] = '0'
            elif mutation == 'outbound':changed['response']['data']['consumption']['outboundRequests'] = 1
            elif mutation == 'fuel':changed['response']['data']['consumption']['cpuFuel'] = '1000000001'
            elif mutation == 'memory':changed['response']['data']['consumption']['peakMemoryBytes'] = '134217729'
            elif mutation == 'known':changed['response']['outcomeKnown'] = False
            elif mutation == 'reaped':changed['processReaped'] = False
            elif mutation == 'decoded':changed['decoded'] = ['1:request-limit:transport-error']
            elif mutation == 'effect':changed['response']['data']['consumption']['effectCount'] = 1
            else:changed['response']['data']['consumption']['outboundRequests'] = False
            with self.subTest(mutation=mutation), self.assertRaises(WorkflowError):
                continuation.preserved_limit(changed, revision, budget)

    def test_only_exact_failed_run_job_artifact_are_eligible(self):
        metadata = {**replay.ARTIFACT, 'expired': False, 'workflow_run': {'id': replay.RUN, 'head_sha': replay.SOURCE}}
        job = {'id': replay.JOB, 'run_id': replay.RUN, 'head_sha': replay.SOURCE, 'status': 'completed', 'conclusion': 'failure'}
        run = {'id': replay.RUN, 'head_sha': replay.SOURCE, 'head_branch': 'feat/dotnet-http-completion-20261021',
            'event': 'workflow_dispatch', 'path': replay.WORKFLOW, 'status': 'completed', 'conclusion': 'failure'}
        replay.validate_origin(metadata, job, run)
        for which, key, value in ((0, 'expired', True), (0, 'digest', 'sha256:'+'0'*64),
                (1, 'head_sha', '0'*40), (1, 'conclusion', 'success'), (2, 'event', 'pull_request'),
                (2, 'path', '.github/workflows/ci.yml'), (2, 'head_branch', 'development')):
            changed = copy.deepcopy([metadata, job, run]);changed[which][key] = value
            with self.subTest(key=key), self.assertRaises(WorkflowError):replay.validate_origin(*changed)

    def test_archive_identity_precedes_extraction_and_regular_shape_refuses_escape_private_or_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(WorkflowError, 'archive-identity'):replay.unpack(b'wrong', Path(temporary))
            for hostile, link in (('managed-http-mixed/build/../../escape', False),
                    ('managed-http-mixed/build/private/key', False), ('managed-http-mixed/build/link', True)):
                data = io.BytesIO()
                with zipfile.ZipFile(data, 'w') as archive:
                    entry = zipfile.ZipInfo(hostile)
                    if link:entry.external_attr = (stat.S_IFLNK | 0o777) << 16
                    archive.writestr(entry, b'public')
                    for index in range(350):archive.writestr('mixed-tools/logs/'+str(index), b'')
                raw = data.getvalue()
                with patch.object(replay, 'ARTIFACT', {'size_in_bytes': len(raw), 'digest': digest(raw)}):
                    with self.subTest(hostile=hostile), self.assertRaisesRegex(WorkflowError, 'public-regular'):
                        replay.unpack(raw, Path(temporary))

    def test_original_controller_application_and_tenant_oracles_are_byte_exact(self):
        for path, expected in (
                ('tools/dotnet_http_mixed_node.py', '30a0662947d502e31cf7e65c5e066c887a499d6079ec2d48d468332c8dd5e5ed'),
                ('tools/dotnet_http_tenant_node.py', '5da8b699e9d49756f4328f0f3a0b3d962647859084fb61e77a10841df78fd7d8'),
                ('tools/fixtures/dotnet-http-mixed/Main.cs', 'bb2a2d62a0d9322861bb999b5da62fe8ec930a4bb09f52311cdd65c148247a54')):
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(), expected)
        self.assertEqual(sum(node.CONTACTS[9:20]), 11)

    def test_default_false_diagnostic_restores_every_original_workflow_step_guard_and_bound(self):
        value = workflow_model((ROOT/replay.WORKFLOW).read_text())
        selection = value['on']['workflow_dispatch']['inputs'].pop('mixed_content_continuation')
        self.assertEqual(selection['type'], 'boolean');self.assertIs(selection['default'], False)
        job = value['jobs'].pop('mixed-content-continuation')
        self.assertEqual(job['if'], "github.event_name == 'workflow_dispatch' && inputs.mixed_content_continuation")
        self.assertEqual(job['timeout-minutes'], 20)
        for name in ('published-http', 'exact-component', 'mixed-content'):
            suffix = ' && !inputs.mixed_content_continuation'
            self.assertTrue(value['jobs'][name]['if'].endswith(suffix))
            value['jobs'][name]['if'] = value['jobs'][name]['if'].removesuffix(suffix)
        old = subprocess.check_output(['git', 'show', replay.SOURCE+':'+replay.WORKFLOW], cwd=ROOT)
        self.assertEqual(value, workflow_model(old.decode()))


if __name__ == '__main__':unittest.main()
