"""Fail-closed same-checkout producer handoff; synthetic logs are not evidence."""
from __future__ import annotations

import copy
import fnmatch
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import (c_timed_current_products as current, ci_lane_inventory,
                   qualify_c_timed_runtime as timed, qualify_host_codec_native as producer)
from tools.phase2_operator_process import WorkflowError
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import write_json


class CurrentTimedProducts(unittest.TestCase):
    def test_current_source_rejects_dirty_or_nonmatching_native_inventory(self):
        head = 'a' * 40
        identity = {'sha256': 'sha256:' + 'b' * 64, 'files': 2, 'bytes': 6}
        def git(*args):
            return (head + '\n').encode() if args == ('rev-parse', 'HEAD') else b''
        with patch.object(current, '_git', side_effect=git), \
                patch.object(current, 'source_identity', return_value=identity), \
                patch.object(current, 'git_source_identity', return_value=identity):
            self.assertEqual(current.current_source(), (head, identity))
        def dirty(*args):
            return (head + '\n').encode() if args == ('rev-parse', 'HEAD') else b'?? changed\n'
        with patch.object(current, '_git', side_effect=dirty), self.assertRaises(WorkflowError):
            current.current_source()
        with patch.object(current, '_git', side_effect=git), \
                patch.object(current, 'source_identity', return_value=identity), \
                patch.object(current, 'git_source_identity', return_value=dict(identity, files=3)), \
                self.assertRaises(WorkflowError):
            current.current_source()

    def test_workflow_keeps_the_original_limits_and_selects_all_current_inputs(self):
        path = current.ROOT / '.github/workflows/c-timed-runtime.yml'
        workflow = ci_lane_inventory.workflow_model(path.read_text())
        paths = workflow['on']['push']['paths']
        selected = set(timed.materials()) | set(producer.materials(producer.ROOT))
        self.assertFalse([name for name in selected
                          if not any(fnmatch.fnmatchcase(name, pattern) for pattern in paths)])
        self.assertEqual(workflow['jobs']['ordinary-c-threads']['timeout-minutes'], 20)
        self.assertEqual(workflow['on']['push']['branches'], ['feat/c-owned-timers-20261022',
                         'fix/c-timed-current-native-20261108'])
        self.assertIn('workflow_dispatch', workflow['on'])
        self.assertFalse(workflow['concurrency']['cancel-in-progress'])
        steps = workflow['jobs']['ordinary-c-threads']['steps']
        artifacts = [step for step in steps if step.get('name') ==
                     'Retain the five verified and size-bounded native products']
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0]['if'], 'success()')
        self.assertEqual(artifacts[0]['with']['retention-days'], 7)
        self.assertEqual(artifacts[0]['with']['if-no-files-found'], 'error')
        self.assertIn('c-thread-native/native-binaries/**', artifacts[0]['with']['path'])
        commands = [step.get('run', '') for step in steps]
        self.assertEqual(sum('--produce-current' in command for command in commands), 1)
        self.assertFalse(any('--current-prepared' in command for command in commands))
        self.assertEqual(len(timed.timed.MODES), 12)

    def test_current_owner_calls_producer_before_consumer_and_fails_closed(self):
        head = 'a' * 40
        with tempfile.TemporaryDirectory() as directory:
            prepared, output = Path(directory) / 'native', Path(directory) / 'result'
            events = []
            with patch.object(timed.sys, 'platform', 'linux'), \
                    patch.object(timed.sys, 'version_info', (3, 13)), \
                    patch.object(timed.os, 'geteuid', return_value=1000, create=True), \
                    patch.object(current, 'current_source', return_value=(head, {})), \
                    patch.object(producer, 'materials', return_value={}), \
                    patch.object(timed, 'materials', return_value={}), \
                    patch.object(current, 'committed_materials'), \
                    patch.object(current, 'historical_coverage'), \
                    patch.object(producer, 'qualify', side_effect=lambda *a: events.append(('produce', a))), \
                    patch.object(timed, '_qualify', side_effect=lambda *a, **k: events.append(('consume', a, k)) or {'status': 'passed'}):
                self.assertEqual(timed.qualify_current(prepared, output, head)['status'], 'passed')
                self.assertEqual(events, [('produce', (prepared, head)),
                                          ('consume', (prepared, output), {'current': True})])
                events.clear()
                with self.assertRaises(WorkflowError):
                    timed.qualify_current(prepared, output, 'b' * 40)
                self.assertEqual(events, [])
                with self.assertRaises(WorkflowError):
                    timed.qualify_current(prepared, prepared / 'result', head)
                self.assertEqual(events, [])
            with patch.object(timed.sys, 'platform', 'linux'), \
                    patch.object(timed.sys, 'version_info', (3, 13)), \
                    patch.object(timed.os, 'geteuid', return_value=1000, create=True), \
                    patch.object(current, 'current_source', return_value=(head, {})), \
                    patch.object(producer, 'materials', return_value={}), \
                    patch.object(timed, 'materials', return_value={}), \
                    patch.object(current, 'committed_materials'), \
                    patch.object(current, 'historical_coverage'), \
                    patch.object(producer, 'qualify', side_effect=ValueError('producer-failed')), \
                    patch.object(timed, '_qualify') as consumer:
                with self.assertRaises(ValueError):
                    timed.qualify_current(prepared, output, head)
                consumer.assert_not_called()

    def test_committed_materials_rejects_missing_or_changed_exact_blob(self):
        head = current._git('rev-parse', 'HEAD').decode('ascii').strip()
        name = 'tools/phase2_operator_process.py'
        identity = file_identity(current.ROOT / name)
        current.committed_materials(head, {name: identity})
        with self.assertRaises(WorkflowError):
            current.committed_materials(head, {name: dict(identity, bytes=identity['bytes'] + 1)})
        with patch.object(current, '_git', return_value=b''), self.assertRaises(WorkflowError):
            current.committed_materials(head, {name: identity})

    def test_product_aggregate_bound_rejects_more_than_512_mib(self):
        identities = {name: {'bytes': size, 'sha256': 'sha256:' + 'a' * 64}
                      for name, size in zip(current.PRODUCTS, (128 * 1024**2,) * 4 + (0,), strict=True)}
        def observed(path, *_args):
            return identities[next(name for name in identities if name.replace('/', '-') == path.name)]
        with patch.object(current, 'file_identity', side_effect=observed):
            self.assertEqual(len(current._products(Path('unused'), identities)), 5)
            last = next(reversed(identities))
            identities[last] = dict(identities[last], bytes=1)
            with self.assertRaises(WorkflowError):
                current._products(Path('unused'), identities)

    def test_failed_verification_never_claims_current_source_verified(self):
        head = 'a' * 40
        proof = {'consumerNativeSource': {}}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(timed.sys, 'platform', 'linux'), \
                patch.object(timed.sys, 'version_info', (3, 13)), \
                patch.object(timed.os, 'geteuid', return_value=1000, create=True):
            failed = Path(directory) / 'failed'
            with patch.object(current, 'native_evidence', side_effect=ValueError('refused')):
                with self.assertRaises(ValueError):
                    timed._qualify(Path(directory) / 'native', failed, current=True)
            self.assertFalse(current.read_json(failed / 'FAILED.json')['nativeProductsCurrentSourceVerified'])
            authenticated = Path(directory) / 'authenticated'
            with patch.object(current, 'native_evidence', return_value=({'compiledSource': head}, proof, {})), \
                    patch.object(timed, 'materials', return_value={}), \
                    patch.object(timed.timed, 'prepare', side_effect=ValueError('later-failure')):
                with self.assertRaises(ValueError):
                    timed._qualify(Path(directory) / 'native', authenticated, current=True)
            self.assertTrue(current.read_json(authenticated / 'FAILED.json')['nativeProductsCurrentSourceVerified'])

    def test_current_inventory_retains_all_historical_controls_and_material_paths(self):
        observed = current.historical_coverage(producer.materials(producer.ROOT))
        self.assertEqual(observed, {'controls': 177, 'materials': 148})
        controls = {stage: (package, needle, list(cases))
                    for stage, package, needle, cases in producer.CONTROLS}
        self.assertEqual(sum(len(row[2]) for row in controls.values()), 251)
        stage = next(stage for stage in controls if stage == 'actual-runtime-timer-strong-weak-owner')
        damaged = list(producer.CONTROLS)
        index = next(index for index, row in enumerate(damaged) if row[0] == stage)
        old = damaged[index]
        damaged[index] = (*old[:3], tuple(case for case in old[3]
            if case != 'activation_runtime::tests::continuations_require_live_original_generation_before_any_admission'))
        with patch.object(producer, 'CONTROLS', tuple(damaged)), self.assertRaises(WorkflowError):
            current.historical_coverage(producer.materials(producer.ROOT))
        paths = producer.materials(producer.ROOT)
        del paths['tools/phase3_resource_identity.py']
        with self.assertRaises(WorkflowError): current.historical_coverage(paths)

    def test_command_handoff_requires_exact_discovery_execution_and_log_identity(self):
        head = 'a' * 40
        cargo = ['cargo', '--config', str(current.ROOT / '.cargo/managed-guest.toml')]
        stages = [('source-revision', ['git', 'rev-parse', 'HEAD'], (head + '\n').encode()),
            ('rust-version', ['rustc', '--version'], b'rustc 1.97.1 (test release)\n'),
            ('normal-host-build', [*cargo, 'build', '--locked', '-p', 'latent', '-p', 'latentd', '--bins',
                '-p', 'latent-packaging', '--example', 'package', '--example', 'capsule_contracts',
                '-p', 'latent-policy', '--example', 'capsule_authoring'], b'')]
        for stage, package, needle, cases in producer.CONTROLS:
            args = [*cargo, 'test', '--locked', '-p', package, '--lib', needle, '--']
            listing = ''.join(case + ': test\n' for case in cases).encode()
            execution = (''.join('test ' + case + ' ... ok\n' for case in cases)
                + f'test result: ok. {len(cases)} passed; 0 failed; 0 ignored;\n').encode()
            stages.extend(((stage + '-list', args + ['--list'], listing),
                           (stage + '-run', args + ['--test-threads=1'], execution)))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'logs').mkdir(); rows = []
            for ordinal, (stage, argv, stdout) in enumerate(stages):
                logs = {}
                for stream, raw in (('stdout', stdout), ('stderr', b'')):
                    relative = f'logs/{ordinal:02d}-{stage}.{stream}.txt'
                    (root / relative).write_bytes(raw)
                    logs[stream] = {'path': relative, **file_identity(root / relative)}
                rows.append({'stage': stage, 'argv': argv, 'exitCode': 0, 'seconds': 0.1, 'logs': logs})
            record = {'sourceRevision': head, 'compiler': 'rustc 1.97.1 (test release)', 'commands': rows}
            current._commands(record, root)
            missing = copy.deepcopy(record); missing['commands'].pop()
            with self.assertRaises(WorkflowError): current._commands(missing, root)
            bad_status = copy.deepcopy(record); bad_status['commands'][4]['exitCode'] = 1
            with self.assertRaises(WorkflowError): current._commands(bad_status, root)
            log = root / rows[4]['logs']['stdout']['path']
            original = log.read_bytes(); log.write_bytes(original.replace(b'... ok', b'... ignored', 1))
            with self.assertRaises(WorkflowError): current._commands(record, root)
            forged = copy.deepcopy(record)
            forged['commands'][4]['logs']['stdout'].update(file_identity(log))
            with self.assertRaises(WorkflowError): current._commands(forged, root)

    def test_native_handoff_rejects_foreign_source_and_changed_binary(self):
        source = {'sha256': 'sha256:' + 'b' * 64, 'files': 1, 'bytes': 5}
        head = 'a' * 40
        materials = {f'material-{index}': {'bytes': 1, 'sha256': 'sha256:' + 'c' * 64}
                     for index in range(151)}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'native-binaries').mkdir()
            binaries = {}
            for original in current.PRODUCTS:
                path = root / 'native-binaries' / original.replace('/', '-')
                path.write_bytes(('product:' + original).encode())
                binaries[original] = file_identity(path)
            snapshot = {'native': source, 'materials': materials}
            record = {'schemaVersion': 'latent.host-codec.native-products.v1', 'status': 'passed',
                'sourceRevision': head, 'source': source, 'materials': materials,
                'compiler': 'rustc 1.97.1 (test release)', 'products': binaries, 'commands': [],
                'controlCount': 251, 'nativeCohort': producer.NATIVE_COHORT,
                'wasmtimeAllocationCohort': producer.codec_wasmtime.COHORT,
                'controls': {stage: list(cases) for stage, _, _, cases in producer.CONTROLS},
                'profile': 'normal-managed-guest-default-features', 'signedQualification': False,
                'guestJavaScriptEngineCompiled': False, 'guestSourceCompiled': False,
                'historicalReceiptRewritten': False, 'scope': current._scope()}
            write_json(root / 'source-inputs.json', snapshot)
            write_json(root / 'native-products.json', record)
            with patch.object(current, 'current_source', return_value=(head, source)), \
                    patch.object(producer, 'materials', return_value=materials), \
                    patch.object(current, 'historical_coverage', return_value={'controls': 177, 'materials': 148}), \
                    patch.object(current, 'committed_materials'), \
                    patch.object(current, '_commands'):
                before, proof, products = current.native_evidence(root)
                self.assertEqual(before['compiledSource'], head)
                self.assertTrue(proof['compiledSourceByteExact'])
                self.assertEqual(set(products), set(current.PRODUCTS.values()))
                path = root / 'native-binaries/latent'
                path.write_bytes(b'changed')
                with self.assertRaises(WorkflowError): current.native_evidence(root)
                path.write_bytes(b'product:latent')
                foreign = dict(record, sourceRevision='d' * 40)
                (root / 'native-products.json').unlink()
                write_json(root / 'native-products.json', foreign)
                with self.assertRaises(WorkflowError): current.native_evidence(root)


if __name__ == '__main__': unittest.main()
