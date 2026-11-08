"""Actual v3 and historical v2 counts remain bound to their own receipts."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import qualify_dotnet_finite_waits as qualification
from tools.dotnet_guest.managed_work import INLINE_PRIMARY_REWRITE_RECEIPT
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT
from tools.tests import test_dotnet_finite_wait_programme as fixtures


class CurrentAggregateFilesystemChain(unittest.TestCase):
    def test_authenticated_v3_helper_count_drives_final_filesystem_chain(self):
        fixture = fixtures.FiniteWaitProgramme()
        self.addCleanup(fixture.doCleanups)
        with tempfile.TemporaryDirectory() as temporary, patch.object(qualification, 'package_identity', return_value={}):
            root = Path(temporary)
            docs, refresh = fixture.build(root)
            before = docs['task-wait-port.json']
            controlled = json.loads((ROOT / 'sdk/dotnet-guest/tests/fixtures/aggregate-task-wait-v2-controlled.json').read_bytes())
            extras = {'profile', 'frameworkInput', 'tool', 'derived', 'sourceCaptureDigest',
                'targetsDigest', 'nativeAotReferenceBinding', 'selection'}
            controlled.update({key: before[key] for key in extras})
            controlled.update(outputDigest=before['outputDigest'], generatedHelperCount=108,
                unchangedOriginalMethods=44708, managedAcceptedWork=copy.deepcopy(INLINE_PRIMARY_REWRITE_RECEIPT))
            docs['task-wait-port.json'] = controlled
            docs['closed-filesystem-port.json']['unchangedBaseMethods'] = 44852
            docs['runtime-profile.json']['profile'] = 'runtime-managed'
            selection = docs['compiler-patches.json']['patches'][0]['selection']
            selection.update(generatedHelperCount=108, aggregateTaskWait=controlled['aggregateTaskWait'])
            def publish(values):
                for name, value in values.items():
                    (root / name).write_bytes((json.dumps(value) + '\n').encode('utf-8'))
                refresh()
            publish(docs)
            qualification.build_evidence(root, aggregate=True)
            for changed in (44851, 44853, True):
                wrong = copy.deepcopy(docs)
                wrong['closed-filesystem-port.json']['unchangedBaseMethods'] = changed
                publish(wrong)
                with self.subTest(changed=changed), self.assertRaises((ValueError, WorkflowError)):
                    qualification.build_evidence(root, aggregate=True)
            wrong = copy.deepcopy(docs)
            wrong['task-wait-port.json']['generatedHelperCount'] = 95
            wrong['compiler-patches.json']['patches'][0]['selection']['generatedHelperCount'] = 95
            publish(wrong)
            with self.assertRaises((ValueError, WorkflowError)):
                qualification.build_evidence(root, aggregate=True)


if __name__ == '__main__':
    unittest.main()
