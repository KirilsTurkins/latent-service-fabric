"""Focused fail-closed controls for the retained-component diagnostic."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import patch
import hashlib
import io
import json
import time
import zipfile

from tools import c_timed_original_trap as diagnostic
from tools.phase2_operator_process import WorkflowError


def encode(value):
    return json.dumps(value, separators=(',', ':')).encode()


def id_row(value):
    return {'digest': diagnostic.identity(value)['sha256'], 'size': len(value)}


def archive_fixture():
    component = b'unchanged-component'
    digest = diagnostic.identity(component)['sha256']
    files = {'component.wasm': component, 'source-inputs.json': b'original-sources'}
    files.update({f'input-{index}.json': str(index).encode() for index in range(12)})
    inventory = {name: id_row(data) for name, data in files.items() if name != 'source-inputs.json'}
    assert len(inventory) == 13
    files['package-inputs.json'] = encode(inventory)
    files['build-observation.json'] = encode({'componentDigest': digest, 'componentSize': len(component)})
    files['BUILD-COMPLETE.json'] = encode({'packageAssembled': True, 'componentDigest': digest,
        'sourceDigest': diagnostic.identity(files['source-inputs.json'])['sha256'],
        'observationDigest': diagnostic.identity(files['build-observation.json'])['sha256']})
    response = {'outcomeKnown': True, 'requestDispatched': True, 'error': {'code': 'guest-trap'},
                'data': {'terminalState': 'guest_trap', 'resolvedRevision': {'releaseDigest': digest}}}
    historical = {'activation': 'c-thread-timed-sleep', 'exitCode': 4, 'processReaped': True,
                  'decoded': None, 'response': response}
    payloads = {'c-thread-runtime/build/' + name: data for name, data in files.items()}
    payloads['c-thread-runtime/node/invocation-c-thread-timed-sleep.json'] = encode(historical)
    sink = io.BytesIO()
    with zipfile.ZipFile(sink, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in payloads.items():
            archive.writestr(name, data)
    raw = sink.getvalue()
    original = {'archiveBytes': len(raw), 'archiveSha256': hashlib.sha256(raw).hexdigest(),
                'members': len(payloads), 'expandedBytes': sum(map(len, payloads.values()))}
    inputs = {name: (len(value), hashlib.sha256(value).hexdigest()) for name, value in files.items()}
    return raw, original, inputs, digest


def empty_snapshot():
    return {'observedErrors': 0, 'ambiguous': False, 'trapKind': None, 'missingBacktrace': False,
            'mayBeTruncated': False, 'observedFrames': 0, 'engineFrameCap': None, 'frames': [None] * 16}


def trap_snapshot():
    result = empty_snapshot()
    result.update(observedErrors=1, trapKind='unreachable-code', observedFrames=1, engineFrameCap=16)
    result['frames'][0] = {'module': 0, 'function': 43, 'moduleOffset': 14604, 'functionOffset': 213}
    return result


def event(snapshot):
    return diagnostic.PREFIX + encode(snapshot) + b'\n'


class ArchiveControls(TestCase):
    def test_exact_archive_and_each_input_are_bound(self):
        raw, origin, inputs, component = archive_fixture()
        with TemporaryDirectory() as root, patch.object(diagnostic, 'ORIGINAL', origin), \
                patch.object(diagnostic, 'INPUTS', inputs), patch.object(diagnostic, 'COMPONENT', component):
            result = diagnostic.restore(raw, Path(root) / 'restored', time.monotonic() + 30)
            self.assertEqual(result['component'], component)
            self.assertEqual((Path(root) / 'restored/component.wasm').read_bytes(), b'unchanged-component')
            self.assertEqual(result['packageInputs'], 13)
            with self.assertRaises(WorkflowError):
                diagnostic.restore(raw[:-1] + bytes([raw[-1] ^ 1]), Path(root) / 'tampered', time.monotonic() + 30)
            bad_inputs = dict(inputs, **{'component.wasm': (len(b'unchanged-component'), '0' * 64)})
            with patch.object(diagnostic, 'INPUTS', bad_inputs), self.assertRaises(WorkflowError):
                diagnostic.restore(raw, Path(root) / 'wrong-input', time.monotonic() + 30)


class SnapshotControls(TestCase):
    def test_real_and_nonreproducing_shapes(self):
        self.assertEqual(diagnostic.numeric_event(b'other line\n' + event(trap_snapshot())), trap_snapshot())
        self.assertEqual(diagnostic.numeric_event(event(empty_snapshot())), empty_snapshot())

    def test_refuses_missing_duplicate_ambiguous_and_private_fields(self):
        bad = trap_snapshot()
        bad['ambiguous'] = True
        private = trap_snapshot()
        private['message'] = 'unretained'
        bad_ordinal = trap_snapshot()
        bad_ordinal['frames'][0]['module'] = 4
        for raw in (b'', event(trap_snapshot()) * 2, event(bad), event(private), event(bad_ordinal),
                    diagnostic.PREFIX + b'{' + b'x' * 4096 + b'}\n'):
            with self.subTest(raw=raw[:80]), self.assertRaises(WorkflowError):
                diagnostic.numeric_event(raw)

    def test_refuses_inconsistent_frame_tail_and_duplicate_json_key(self):
        bad = trap_snapshot()
        bad['frames'][1] = bad['frames'][0]
        for raw in (event(bad), diagnostic.PREFIX + b'{"observedErrors":0,"observedErrors":1}\n'):
            with self.subTest(raw=raw[:80]), self.assertRaises(WorkflowError):
                diagnostic.numeric_event(raw)


class ReplayControls(TestCase):
    def exercise(self, disposition):
        class Process:
            buffers = [bytearray(), bytearray(event(trap_snapshot() if disposition == 'trap' else empty_snapshot()))]
            def drain(self):
                pass
        calls = []

        def original_invoke(client, probe, target, output, mode, activation):
            calls.append((mode, activation))
            response = {'outcomeKnown': True, 'requestDispatched': True,
                        'data': {'resolvedRevision': {'releaseDigest': diagnostic.COMPONENT}}}
            if disposition == 'trap':
                response.update(error={'code': 'guest-trap', 'details': [
                    {'kind': 'activation.guest-trap-kind', 'fields': {'kind': 'unreachable-code'}}]})
                response['data']['terminalState'] = 'guest_trap'
            row = {'activation': activation, 'exitCode': 4 if disposition == 'trap' else 0,
                   'processReaped': True, 'response': response}
            (output / ('invocation-' + activation + '.json')).write_bytes(encode(row))
            if disposition == 'trap':
                raise WorkflowError('c-timed-ordinary-success')
            return {'originalResultPassed': True}

        def original_programme(client, process, probe, manifest, target, output):
            calls.extend(('original-prefix', index) for index in range(20))
            return diagnostic.node.invoke_timed(client, probe, target, output, 'timed-sleep', 'c-thread-timed-sleep')

        def run(artifact, native, output):
            output.mkdir()
            settings = {'engine': {'threadingProfile': 'c-context144-sync-cooperative-v1'},
                        'providers': {'activationRuntime': {'limits': diagnostic.LIMITS, 'nativeThreads': True}},
                        'workers': {'runtime': 1, 'control': 1}, 'cells': [{'class': 'standard', 'capacity': 1,
                            'queueCapacity': 2, 'maximumMemoryBytes': 67_108_864}]}
            diagnostic.node.configure(settings, {})
            try:
                return diagnostic.node.programme(None, Process(), None, None, {'budget': diagnostic.BUDGET}, output)
            finally:
                (output / 'FAILED.json').write_bytes(encode({'status': 'failed', 'stage': 'ordinary-c-thread-lifecycle'}))

        with TemporaryDirectory() as root, patch.object(diagnostic.node, 'run', run), \
                patch.object(diagnostic.node, 'programme', original_programme), \
                patch.object(diagnostic.node, 'invoke_timed', original_invoke), \
                patch.object(diagnostic.node, 'configure', lambda settings, capsule: settings):
            result = diagnostic.replay(Path(root), {}, Path(root) / 'node')
        self.assertEqual(len(calls), 21)
        self.assertTrue(result['originalTwentyControlsPassed'])
        return result

    def test_original_trap_assertion_stays_a_failure_and_is_observed(self):
        result = self.exercise('trap')
        self.assertEqual(result['status'], 'target-original-success-assertion-failed')
        self.assertEqual(result['event']['trapKind'], 'unreachable-code')

    def test_target_success_is_nonreproduction_and_stops_later_cases(self):
        result = self.exercise('success')
        self.assertEqual(result['status'], 'target-completed')
        self.assertEqual(result['event']['observedErrors'], 0)

    def test_unrelated_prefix_failure_is_not_classified_as_target(self):
        def fail(*args):
            raise WorkflowError('original-prefix-failure')
        def run(artifact, native, output):
            output.mkdir()
            settings = {'engine': {'threadingProfile': 'c-context144-sync-cooperative-v1'},
                        'providers': {'activationRuntime': {'limits': diagnostic.LIMITS, 'nativeThreads': True}},
                        'workers': {'runtime': 1, 'control': 1}, 'cells': [{'class': 'standard', 'capacity': 1,
                            'queueCapacity': 2, 'maximumMemoryBytes': 67_108_864}]}
            diagnostic.node.configure(settings, {})
            return diagnostic.node.programme(None, None, None, None, {'budget': diagnostic.BUDGET}, output)
        with TemporaryDirectory() as root, patch.object(diagnostic.node, 'run', run), \
                patch.object(diagnostic.node, 'programme', fail), \
                patch.object(diagnostic.node, 'configure', lambda settings, capsule: settings):
            with self.assertRaisesRegex(WorkflowError, 'original-prefix-failure'):
                diagnostic.replay(Path(root), {}, Path(root) / 'node')

    def test_wrong_runtime_limit_or_activation_budget_refuses_before_prefix(self):
        def run_with(change):
            def run(artifact, native, output):
                output.mkdir()
                settings = {'engine': {'threadingProfile': 'c-context144-sync-cooperative-v1'},
                            'providers': {'activationRuntime': {'limits': dict(diagnostic.LIMITS), 'nativeThreads': True}},
                            'workers': {'runtime': 1, 'control': 1}, 'cells': [{'class': 'standard', 'capacity': 1,
                                'queueCapacity': 2, 'maximumMemoryBytes': 67_108_864}]}
                budget = dict(diagnostic.BUDGET)
                change(settings, budget)
                diagnostic.node.configure(settings, {})
                diagnostic.node.programme(None, None, None, None, {'budget': budget}, output)
            return run
        for change in (lambda settings, budget: settings['providers']['activationRuntime']['limits'].update(waits=17),
                       lambda settings, budget: budget.update(memoryBytes=33_554_433)):
            with self.subTest(change=change), TemporaryDirectory() as root, \
                    patch.object(diagnostic.node, 'run', run_with(change)), \
                    patch.object(diagnostic.node, 'programme', lambda *args: self.fail('prefix must not run')), \
                    patch.object(diagnostic.node, 'configure', lambda settings, capsule: settings):
                with self.assertRaises(WorkflowError):
                    diagnostic.replay(Path(root), {}, Path(root) / 'node')

    def test_node_opt_in_is_scoped_to_spawn_and_restored_on_failure(self):
        for fail_spawn in (False, True):
            client = SimpleNamespace(environment={'PATH': '/usr/bin'})
            observed = []
            def original_connect(passed_client):
                observed.append(dict(passed_client.environment))
                if fail_spawn:
                    raise WorkflowError('node-spawn-refused')
                return object()
            def run(artifact, native, output):
                diagnostic.node.connect(client)
                raise WorkflowError('stop-before-prefix')
            with self.subTest(fail_spawn=fail_spawn), TemporaryDirectory() as root, \
                    patch.object(diagnostic.node, 'run', run), patch.object(diagnostic.node, 'connect', original_connect):
                with self.assertRaises(WorkflowError):
                    diagnostic.replay(Path(root), {}, Path(root) / 'node')
            self.assertEqual(observed[0]['LSF_C_TIMED_ORIGINAL_TRAP'], '1')
            self.assertEqual(client.environment, {'PATH': '/usr/bin'})


if __name__ == '__main__':
    main()
