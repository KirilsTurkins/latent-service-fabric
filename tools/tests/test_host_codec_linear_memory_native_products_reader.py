"""Unfrozen v7 literal/schema controls only; no native acquisition or result."""
import ast
import copy
import subprocess
import unittest

from tools import host_codec_linear_memory_native_products_reader as owner
from tools import host_codec_funcrefs_native_products_reader as previous
from tools import sdk_native_products_reader as fixed
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT
from tools.tests.test_host_codec_funcrefs_native_products_reader import model as previous_model
from tools.tests.test_host_codec_funcrefs_native_products_reader import source_model as previous_source

SOURCE_MODEL = 'f5351a9331ed954c49ae83f2f4004e0f96d25d0e'
PREVIOUS_UNFROZEN_MODEL = 'ea118974d93843265a504f5d30571ed7cfe8a7d2'


def source_model():
    return subprocess.check_output(
        ['git', 'show', SOURCE_MODEL + ':tools/qualify_host_codec_native.py'], cwd=ROOT)


def model():
    _, record, snapshot, native, materials = previous_model()
    reader = object.__new__(owner.FrozenHostCodecLinearMemoryProducts)
    reader.source = SOURCE_MODEL
    reader.controls, reader.recipe = owner.producer_contract(source_model())
    reader.stages = ('source-revision', 'rust-version', 'normal-host-build',
        *(stage + suffix for stage, _, _, _ in reader.controls for suffix in ('-list', '-run')))
    cargo = ['cargo', '--config', '/controlled/source/.cargo/managed-guest.toml']
    commands = [row['argv'] for row in record['commands'][:3]]
    for _, package, needle, _ in reader.controls:
        args = [*cargo, 'test', '--locked', '-p', package, '--lib', needle, '--']
        commands.extend([args + ['--list'], args + ['--test-threads=1']])
    record.update(sourceRevision=SOURCE_MODEL, controlCount=114,
        nativeCohort=owner.COHORT, scope=owner.SCOPE,
        controls={stage: list(cases) for stage, _, _, cases in reader.controls},
        commands=[{'stage': stage, 'argv': argv, 'exitCode': 0, 'seconds': .1,
            'logs': {stream: {'path': f'logs/{index:02d}-{stage}.{stream}.txt',
                'bytes': 0, 'sha256': 'sha256:' + '0' * 64} for stream in ('stdout', 'stderr')}}
            for index, (stage, argv) in enumerate(zip(reader.stages, commands))])
    return reader, record, snapshot, native, materials


class HostCodecLinearMemoryProductsReaderControls(unittest.TestCase):
    # Historical case identifiers remain append-only; the unfrozen literals
    # and all assertions below are retargeted to the reviewed v7 contract.
    def test_exact_v6_literal_contract_keeps_the_original_prefix_and_three_audit_cases(self):
        raw = source_model()
        controls, recipe = owner.producer_contract(raw)
        old, old_recipe = previous.producer_contract(previous_source())
        self.assertEqual((len(controls), sum(len(row[3]) for row in controls), len(recipe)), (24, 114, 22))
        self.assertEqual(controls[:20], old)
        raw103 = subprocess.check_output(['git', 'show', PREVIOUS_UNFROZEN_MODEL + ':tools/qualify_host_codec_native.py'], cwd=ROOT)
        from tools.host_codec_native_products_reader import _producer_contract
        old103, _ = _producer_contract(raw103, 23, 103)
        self.assertEqual(controls[:23], old103)
        with self.assertRaises(WorkflowError):
            owner.producer_contract(raw103)
        self.assertEqual(recipe, old_recipe)
        self.assertEqual(controls[-2][1:3], ('latent-audit', 'native_thread_audit_'))
        self.assertEqual(controls[-2][3], (
            'durable::tests::capability::native_thread_audit_encodes_exact_grant_and_host_completion_without_changing_default_abi',
            'durable::tests::capability::native_thread_audit_refuses_other_versions_operations_and_resource_classes',
            'durable::tests::capability::native_thread_audit_retains_identity_outcome_and_redaction_boundaries'))
        self.assertEqual(controls[-1][:3], ('retained-activation-context', 'latent-wasmtime', 'host::owned_context::tests::'))
        self.assertEqual(len(controls[-1][3]), 11)
        scopes = [ast.literal_eval(value) for node in ast.walk(ast.parse(raw))
            if isinstance(node, ast.Dict) for key, value in zip(node.keys, node.values)
            if isinstance(key, ast.Constant) and key.value == 'scope']
        self.assertEqual(scopes, [owner.SCOPE])
        for invalid in (b'', raw + b'\nCONTROLS = ()\n',
                raw.replace(b"'tools/build_process_signals.py',", b'', 1),
                raw.replace(b"'native-thread-audit-codec'", b"'original-host-memory'", 1)):
            self.assertTrue(invalid != raw, 'adverse must change the source preimage')
            with self.assertRaises(WorkflowError):
                owner.producer_contract(invalid)
        with self.assertRaises(WorkflowError):
            previous.producer_contract(raw)

    def test_whole_v6_model_refuses_partial_records_wrong_sources_cohorts_and_command_claims(self):
        reader, record, snapshot, native, materials = model()
        reader.validate_record(record, snapshot, native, materials)
        for kind in ('old-cohort', 'old-scope', 'old-count', 'count-bool', 'missing-control',
                'missing-command', 'extra-command', 'reordered', 'failed-command', 'wrong-command',
                'missing-stream', 'extra-time', 'qualification', 'foreign-source', 'foreign-material'):
            bad = copy.deepcopy(record)
            if kind == 'old-cohort': bad['nativeCohort'] = previous.COHORT
            elif kind == 'old-scope': bad['scope'] = previous.SCOPE
            elif kind == 'old-count': bad['controlCount'] = 103
            elif kind == 'count-bool': bad['controlCount'] = True
            elif kind == 'missing-control': bad['controls'].pop(reader.controls[-1][0])
            elif kind == 'missing-command': bad['commands'].pop()
            elif kind == 'extra-command': bad['commands'].append(bad['commands'][-1])
            elif kind == 'reordered': bad['commands'][-1], bad['commands'][-2] = bad['commands'][-2:]
            elif kind == 'failed-command': bad['commands'][-1]['exitCode'] = 1
            elif kind == 'wrong-command': bad['commands'][-1]['argv'][-1] = '--ignored'
            elif kind == 'missing-stream': del bad['commands'][-1]['logs']['stderr']
            elif kind == 'extra-time': bad['commands'][-1]['seconds'] = 1321
            elif kind == 'qualification': bad['signedQualification'] = True
            elif kind == 'foreign-source': bad['sourceRevision'] = '0' * 40
            else: bad['materials'] = {}
            with self.subTest(kind=kind), self.assertRaises(WorkflowError):
                reader.validate_record(bad, snapshot, native, materials)
        old, old_record, old_snapshot, old_native, old_materials = previous_model()
        old.validate_record(old_record, old_snapshot, old_native, old_materials)
        with self.assertRaises(WorkflowError):
            old.validate_record(record, snapshot, native, materials)
        with self.assertRaises(WorkflowError):
            reader.validate_record(old_record, old_snapshot, old_native, old_materials)

    def test_shared_acquisition_is_unchanged_and_no_unfrozen_module_can_prepare_products(self):
        current = object.__new__(owner.FrozenHostCodecLinearMemoryProducts)
        self.assertEqual(current._producer_origin(), ('.github/workflows/host-codec-memory.yml',
            'Original ledger codec table Store registry FuncRefs resource context ownership and diagnostics',
            'host-codec-memory-'))
        self.assertEqual((current.control_count, current.command_count), (114, 51))
        for name in ('prepare', 'verify_prepared', 'extract', 'preflight'):
            self.assertIs(getattr(owner.FrozenHostCodecLinearMemoryProducts, name),
                          getattr(fixed.FrozenNativeProducts, name))
        for name in ('SOURCE', 'RUN', 'JOB', 'ARTIFACT', 'prepare', 'native_products'):
            self.assertFalse(hasattr(owner, name), name)


if __name__ == '__main__':
    unittest.main()
