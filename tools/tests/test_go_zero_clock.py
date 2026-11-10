"""Fail-closed evidence controls for the finite zero-origin Go timer."""
import json
import tempfile
from pathlib import Path
import unittest

from tools import qualify_go_synchronization as owner
from tools import qualify_go_activation as activation


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


def ticker_output():
    row = dict(case='zero-clock-ticker-coalescing', outcome='success', pendingDeadlines=[5, 10, 30],
               advances=[5, 29, 30], nominalMissedPeriods=3, liveStores=0, liveInstances=0,
               reservations=0, reservedFuel=0, reservedMemory=0, pendingProviderWaits=0)
    return ('\n'.join([f'test {owner.TICKER_CLOCK_CASE} ... ok',
                       'GO_TICKER_CATCHUP_CASE ' + json.dumps(row),
                       'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 38 filtered out;']) + '\n').encode()


def ticker_witness():
    return (b'LSF-GO-NODE-STOP-TIMER-V1|pending|start-accepted|1|1|0|1\n'
            b'LSF-GO-NODE-STOP-TIMER-V1|pending|next-entered|2|1|1|1\n'
            b'LSF-GO-TICKER-CLOCK-V1|wait-pending|0|5\n'
            b'LSF-GO-TICKER-CLOCK-V1|advance|0|5\n'
            b'LSF-GO-NODE-STOP-TIMER-V1|pending|next-entered|3|1|1|1\n'
            b'LSF-GO-TICKER-CLOCK-V1|wait-pending|5|10\n'
            b'LSF-GO-TICKER-CLOCK-V1|advance|5|29\n'
            b'LSF-GO-NODE-STOP-TIMER-V1|pending|next-entered|4|1|1|1\n'
            b'LSF-GO-TICKER-CLOCK-V1|wait-pending|29|30\n'
            b'LSF-GO-TICKER-CLOCK-V1|advance|29|30\n'
            b'LSF-GO-NODE-STOP-TIMER-V1|pending|root-close|5|1|0|0\n')


def wall_output():
    row = dict(case='pending-timer-wall-jumps', outcome='success', wallOffsetsMillis=[60000, -60000],
               monotonicBefore=0, monotonicAfter=5, sameWaitRepolls=2, liveStores=0, liveInstances=0,
               reservations=0, reservedFuel=0, reservedMemory=0, pendingProviderWaits=0)
    return ('\n'.join([f'test {owner.WALL_CLOCK_CASE} ... ok',
                       'GO_WALL_CLOCK_CASE ' + json.dumps(row),
                       'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 39 filtered out;']) + '\n').encode()


def wall_witness():
    return (b'LSF-GO-NODE-STOP-TIMER-V1|pending|start-accepted|1|1|0|1\n'
            b'LSF-GO-NODE-STOP-TIMER-V1|pending|next-entered|2|1|1|1\n'
            b'LSF-GO-ZERO-CLOCK-V1|wait-pending|0|5\n'
            b'LSF-GO-WALL-CLOCK-V1|jump|1|0\n'
            b'LSF-GO-WALL-CLOCK-V1|repoll|1|0|5\n'
            b'LSF-GO-WALL-CLOCK-V1|jump|2|0\n'
            b'LSF-GO-WALL-CLOCK-V1|repoll|2|0|5\n'
            b'LSF-GO-WALL-CLOCK-V1|restore|0\n'
            b'LSF-GO-WALL-CLOCK-V1|advance|0|5\n'
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


    def test_ticker_campaign_reuses_the_source_bound_zero_clock_component(self):
        path = Path('fixture')
        self.assertEqual(owner.campaign('ticker-clock-v7', path, None),
            {'case': owner.TICKER_CLOCK_CASE, 'fixture': 'zero-clock',
             'variable': 'LSF_GO_V7_ZERO_CLOCK_FIXTURE',
             'inputs': [(path, 'go-component-activation-v7')]})
        with self.assertRaises(ValueError):
            owner.campaign('ticker-clock-v7', path, Path('unexpected'))

    def test_ticker_requires_all_three_ordered_original_waits(self):
        result = owner.ticker_clock_observations(ticker_output(), ticker_witness(), 38)
        self.assertEqual(result['cases'][0]['pendingDeadlines'], [5, 10, 30])
        lines = ticker_witness().splitlines(keepends=True)
        bad = [b''.join(lines[:4]+lines[5:]),
               b''.join(lines[:5]+[lines[5], lines[5]]+lines[6:]),
               b''.join(lines[:5]+[lines[6], lines[5]]+lines[7:]),
               ticker_witness().replace(b'wait-pending|29|30', b'wait-pending|29|15'),
               ticker_witness().replace(b'advance|5|29', b'advance|5|30'),
               ticker_witness().replace(b'next-entered|3|1|1|1', b'next-entered|3|1|0|1'),
               ticker_witness().replace(b'root-close|5|1|0|0', b'root-close|5|1|1|0')]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                owner.ticker_clock_observations(ticker_output(), value, 38)

    def test_ticker_rejects_duplicate_or_foreign_results_and_unsettled_owners(self):
        bad = [ticker_output().replace(owner.TICKER_CLOCK_CASE.encode(), b'foreign'),
               ticker_output().replace(b'"nominalMissedPeriods": 3', b'"nominalMissedPeriods": 2'),
               ticker_output().replace(b'"nominalMissedPeriods": 3', b'"nominalMissedPeriods": 3, "nominalMissedPeriods": 3'),
               ticker_output().replace(b'"liveStores": 0', b'"liveStores": 1'),
               ticker_output()+ticker_output()]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                owner.ticker_clock_observations(value, ticker_witness(), 38)
        with self.assertRaises(ValueError):
            owner.ticker_clock_observations(ticker_output(), ticker_witness(), 39)


    def test_wall_campaign_reuses_the_source_bound_zero_clock_component(self):
        path = Path('fixture')
        self.assertEqual(owner.campaign('wall-clock-v7', path, None),
            {'case': owner.WALL_CLOCK_CASE, 'fixture': 'zero-clock',
             'variable': 'LSF_GO_V7_ZERO_CLOCK_FIXTURE',
             'inputs': [(path, 'go-component-activation-v7')]})
        with self.assertRaises(ValueError):
            owner.campaign('wall-clock-v7', path, Path('unexpected'))

    def test_wall_witness_requires_two_ordered_repolls_of_one_wait(self):
        observed = owner.wall_clock_observations(wall_output(), wall_witness(), 39)
        self.assertEqual(observed['cases'][0]['wallOffsetsMillis'], [60000, -60000])
        lines = wall_witness().splitlines(keepends=True)
        bad = [b''.join(lines[:4] + lines[5:]),
               b''.join(lines[:5] + [lines[5], lines[5]] + lines[6:]),
               b''.join(lines[:3] + [lines[4], lines[3]] + lines[5:]),
               wall_witness().replace(b'repoll|2|0|5', b'repoll|2|1|5'),
               wall_witness().replace(b'advance|0|5', b'advance|0|4'),
               wall_witness().replace(b'next-entered|2|1|1|1', b'next-entered|2|1|0|1'),
               wall_witness().replace(b'root-close|3|1|0|0', b'root-close|3|1|1|0')]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                owner.wall_clock_observations(wall_output(), value, 39)

    def test_wall_rejects_duplicate_foreign_or_unsettled_results(self):
        bad = [wall_output().replace(owner.WALL_CLOCK_CASE.encode(), b'foreign'),
               wall_output().replace(b'"sameWaitRepolls": 2', b'"sameWaitRepolls": 1'),
               wall_output().replace(b'"sameWaitRepolls": 2', b'"sameWaitRepolls": 2, "sameWaitRepolls": 2'),
               wall_output().replace(b'"liveStores": 0', b'"liveStores": 1'),
               wall_output().replace(b'"monotonicBefore": 0', b'"monotonicBefore": false'),
               wall_output() + wall_output()]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                owner.wall_clock_observations(value, wall_witness(), 39)
        with self.assertRaises(ValueError):
            owner.wall_clock_observations(wall_output(), wall_witness(), 40)

    def test_native_ticker_reference_is_strictly_parsed_and_source_bound(self):
        def encoded(rows):
            return b'\n'.join(json.dumps(row).encode() for row in rows) + b'\n'
        package, case = 'command-line-arguments', activation.TICKER_REFERENCE_CASE
        rows = [dict(Package=package, Action='start'), dict(Package=package, Action='run', Test=case),
                dict(Package=package, Action='pass', Test=case), dict(Package=package, Action='pass')]
        self.assertTrue(activation.ticker_reference_result(encoded(rows)))
        for bad in (rows[:-1], rows+[rows[-1]], [rows[0]]+rows, [dict(rows[0], Action='skip')]+rows[1:],
                    [dict(rows[0], Package='foreign')]+rows[1:]):
            with self.assertRaises(ValueError): activation.ticker_reference_result(encoded(bad))
        with self.assertRaisesRegex(ValueError, 'duplicate-field'):
            activation.ticker_reference_result(b'{"Package":"command-line-arguments","Action":"pass","Action":"fail"}')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / activation.TICKER_REFERENCE
            source.parent.mkdir(parents=True)
            source.write_bytes(b'reviewed native fixture')
            native = {'tickerReference': {'case': case, 'sourceDigest': 'sha256:' + owner.digest(source.read_bytes()),
                                          'fakeClock': 'go-testing-synctest', 'passed': True}}
            owner.require_ticker_native_reference(native, root)
            for bad in ({}, {'tickerReference': dict(native['tickerReference'], passed=1)},
                        {'tickerReference': dict(native['tickerReference'], sourceDigest='sha256:changed')}):
                with self.assertRaises(ValueError): owner.require_ticker_native_reference(bad, root)
