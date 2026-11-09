"""Fail-closed evidence controls for the finite zero-origin Go timer."""
import json
import tempfile
from pathlib import Path
import unittest

from tools import qualify_go_synchronization as owner


def signed_output():
    row = dict(case='zero-to-five-nanoseconds', outcome='success', rawBefore=0, rawAfter=5,
               pendingOriginalWait=True, liveStores=0, liveInstances=0, reservations=0,
               reservedFuel=0, reservedMemory=0, pendingProviderWaits=0)
    return ('\n'.join([f'test {owner.ZERO_CLOCK_CASE} ... ok',
                       'GO_ZERO_CLOCK_CASE ' + json.dumps(row),
                       'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 37 filtered out;']) + '\n').encode()


def witness():
    return (b'LSF-GO-NODE-STOP-TIMER-V1|pending|start-accepted|1|1|0|1\n'
            b'LSF-GO-NODE-STOP-TIMER-V1|pending|next-entered|2|1|1|1\n'
            b'LSF-GO-ZERO-CLOCK-V1|wait-pending|0|5\n'
            b'LSF-GO-ZERO-CLOCK-V1|advance|0|5\n'
            b'LSF-GO-NODE-STOP-TIMER-V1|pending|root-close|3|1|0|0\n')


class ZeroClockControls(unittest.TestCase):
    def test_only_exact_v7_campaign_is_selected(self):
        path = Path('fixture')
        self.assertEqual(owner.campaign('zero-clock-v7', path, None),
            {'case': owner.ZERO_CLOCK_CASE, 'fixture': 'zero-clock',
             'variable': 'LSF_GO_V7_ZERO_CLOCK_FIXTURE',
             'inputs': [(path, 'go-component-activation-v7')]})
        with self.assertRaisesRegex(ValueError, 'unreviewed-campaign'):
            owner.campaign('zero-clock-v7', path, Path('unexpected'))

    def test_compiler_identity_rejects_changed_source_wit_component_and_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'root'
            built = Path(temporary) / 'build'
            original = root / 'sdk/go-guest/runtime/zero-clock-conformance'
            for folder in (original, built / 'src', built / 'wit', built / 'build'):
                folder.mkdir(parents=True)
            source, wit, component = b'ordinary zero-clock source', b'fixed world', b'component bytes'
            (original / 'main.go').write_bytes(source)
            (original / 'world.wit').write_bytes(wit)
            (built / 'src/main.go').write_bytes(source)
            (built / 'wit/world.wit').write_bytes(wit)
            (built / 'build/component.wasm').write_bytes(component)
            record = dict(profile='go-component-activation-v7', fixture='zero-clock',
                sourceDigest='sha256:' + owner.digest(source), sourceUnchanged=True, ordinarySource=True,
                signedExecution='not-run', componentDigest='sha256:' + owner.digest(component),
                bindingDigest='test-binding', tools={}, transformations=[],
                nativeReference=dict(modes=[0], output=42, freshProcessPerMode=True,
                                     sourceDigest='sha256:' + owner.digest(source)))
            (built / 'GO-ACTIVATION-COMPILE.json').write_text(json.dumps(record))
            accepted = owner.compile_identity(built, root, 'go-component-activation-v7', 'zero-clock')
            self.assertEqual(accepted['sourceDigest'], record['sourceDigest'])
            for target in [built / 'src/main.go', built / 'wit/world.wit', built / 'build/component.wasm']:
                old = target.read_bytes()
                target.write_bytes(old + b'changed')
                with self.subTest(target=target.name), self.assertRaises(ValueError):
                    owner.compile_identity(built, root, 'go-component-activation-v7', 'zero-clock')
                target.write_bytes(old)
            with self.assertRaises(ValueError):
                owner.compile_identity(built, root, 'go-component-activation-v5', 'zero-clock')

    def test_rejects_missing_duplicate_or_reordered_owner_edges(self):
        self.assertEqual(owner.zero_clock_observations(signed_output(), witness(), 37)['cases'][0]['rawAfter'], 5)
        original = witness().splitlines(keepends=True)
        invalid = [
            b''.join(original[:1] + original[2:]),
            b''.join(original[:2] + [original[2], original[2]] + original[3:]),
            b''.join(original[:2] + [original[3], original[2]] + original[4:]),
            witness().replace(b'next-entered|2|1|1|1', b'next-entered|2|1|0|1'),
            witness().replace(b'start-accepted|1|1|0|1', b'start-accepted|1|1|0|2'),
            witness().replace(b'root-close|3|1|0|0', b'root-close|3|1|1|0'),
            witness().replace(b'wait-pending|0|5', b'wait-pending|1|5'),
            witness().replace(b'advance|0|5', b'advance|0|4'),
        ]
        for bad in invalid:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                owner.zero_clock_observations(signed_output(), bad, 37)

    def test_rejects_wrong_case_result_and_retirement(self):
        bad_outputs = [
            signed_output().replace(owner.ZERO_CLOCK_CASE.encode(), b'other'),
            signed_output().replace(b'"rawBefore": 0', b'"rawBefore": 1'),
            signed_output().replace(b'"pendingOriginalWait": true', b'"pendingOriginalWait": false'),
            signed_output().replace(b'"liveStores": 0', b'"liveStores": 1'),
            signed_output().replace(b'"rawAfter": 5', b'"rawAfter": 5, "rawAfter": 5'),
            signed_output() + signed_output(),
        ]
        for bad in bad_outputs:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                owner.zero_clock_observations(bad, witness(), 37)
        with self.assertRaises(ValueError):
            owner.zero_clock_observations(signed_output(), witness(), 38)
