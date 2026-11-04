"""Retained original-v3 observations, not runtime or cause qualification."""
import hashlib
import json
from pathlib import Path
import unittest
from tools import dotnet_original_fault as observer


class OriginalDotnetEvidenceTests(unittest.TestCase):
    def test_retained_receipts_match_the_authenticated_artifact_members(self):
        directory = Path(__file__).resolve().parents[2] / 'docs/testing/evidence'
        manifest = json.loads((directory / 'dotnet-original-v3-2026-10-31.2a79e99.json').read_bytes())
        self.assertEqual((manifest['runId'], manifest['jobId'], manifest['artifactId']),
                         (41231638834, 124626901570, 13053659402))
        self.assertEqual(manifest['sourceCommit'], '2a79e99443c534cdbbb5ef97ef608b591e416d2f')
        self.assertEqual(manifest['artifactBytes'], 1281439)
        self.assertEqual(manifest['artifactSha256'], 'e05333c1a16b529289d3b34181124756697157cb285cd8633720c335af7dfa8b')
        self.assertIs(manifest['workflowPassed'], True)
        expected = {
            'ADMISSION.json': (7945, '34daf848797a777ce8983986954b6912745b2906e31a01eaf61bba6e05e5a9d4'),
            'observation-result.json': (12382, 'fe3bdea0785bb6fdbe0f966e4ad009b4e96fdaebec9156207e11f4afea12e3c4'),
            'commands/logs/12-execute-1.stdout.txt': (3549, 'd9064cd2cb1757c81d04a4ed801b5158c1f325a204f60b4db6678b25f818772a'),
        }
        self.assertEqual(set(manifest['receipts']), set(expected))
        content = {}
        for name, (size, digest) in expected.items():
            row = manifest['receipts'][name]
            self.assertEqual(Path(row['file']).name, row['file'])
            raw = (directory / row['file']).read_bytes()
            self.assertEqual((row['bytes'], row['sha256']), (size, digest))
            self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), (size, digest))
            content[name] = raw
        admission = json.loads(content['ADMISSION.json'])
        self.assertIs(admission['productExecutionPermission'], False)
        members = {row['path']: row for row in admission['files']}
        self.assertEqual(len(members), len(admission['files']))
        for name in expected.keys() - {'ADMISSION.json'}:
            self.assertEqual((members[name]['bytes'], members[name]['sha256']),
                             (expected[name][0], 'sha256:' + expected[name][1]))
        receipt = json.loads(content['observation-result.json'])
        self.assertEqual(receipt['sourceRevision'], manifest['sourceCommit'])
        self.assertEqual(receipt['observations'], observer.observations(content['commands/logs/12-execute-1.stdout.txt']))

    def test_retained_observation_preserves_identity_bounds_and_nonqualification(self):
        directory = Path(__file__).resolve().parents[2] / 'docs/testing/evidence'
        receipt = json.loads((directory / 'dotnet-original-v3-2026-10-31.2a79e99.observation.json').read_bytes())
        self.assertEqual(receipt['status'], 'captured-nonqualifying')
        self.assertEqual(receipt['original']['origin'], observer.ORIGINAL)
        self.assertEqual(receipt['original']['component'], observer.COMPONENT)
        self.assertEqual(receipt['ownerCaps'], observer.OWNER_CAPS)
        for flag in ('runtimeQualification', 'full746Qualified', 'fullAC7Qualified',
                     'originalFaultCauseQualified', 'opaqueCauseQualified',
                     'physicalRetirementQualified', 'nativeAccountingComplete',
                     'guestCompilerCorelibRebuilt', 'auxiliaryRewritePerformed',
                     'normal15OutcomeReceiptChanged', 'hermetic', 'implicitCompilerInputsAttested'):
            self.assertIs(receipt[flag], False, flag)
        self.assertIs(receipt['sourceBeforeEqualsAfter'], True)
        self.assertIs(receipt['diagnosticIoMayPerturbTimingAndTerminalObservation'], True)
        self.assertEqual(receipt['limits'], dict(absoluteSeconds=1320, commandSeconds=600,
            cleanupReserveSeconds=5, jobs=2, commandCount=128,
            diagnosticBytes=16777216, publicBytes=134217728))
        self.assertLessEqual(receipt['commandCount'], receipt['limits']['commandCount'])
        self.assertLessEqual(receipt['diagnosticBytes'], receipt['limits']['diagnosticBytes'])
        traps = [row['observation']['observation'] for row in receipt['observations'] if row['kind'] == 'DOTNET_ORIGINAL_V3_TRAP']
        self.assertEqual(len(traps), 2)
        for trap in traps:
            self.assertEqual(trap['observedFrames'], 12)
            self.assertIs(trap['mayBeTruncated'], False)
        left, right = [trap['frames'] for trap in traps]
        self.assertEqual(left[:9], right[:9])
        self.assertEqual(left[10:], right[10:])
        self.assertEqual((left[9]['function'], right[9]['function']), (1314, 1314))
        self.assertEqual((left[9]['functionOffset'], right[9]['functionOffset']), (1109, 1413))
