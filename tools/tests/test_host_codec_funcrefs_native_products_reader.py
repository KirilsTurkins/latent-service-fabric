"""Literal v4 producer/schema models only; no native outcome or acquisition."""
import ast
import copy
import subprocess
import unittest

from tools import host_codec_funcrefs_native_products_reader as owner
from tools import host_codec_native_products_reader as original
from tools import host_codec_table_store_native_products_reader as table_store
from tools import sdk_native_products_reader as fixed
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT
from tools.tests.test_host_codec_native_products_reader import model as original_model
from tools.tests.test_host_codec_table_store_native_products_reader import (
    model as table_store_model, source_model as table_store_source)

SOURCE_MODEL = '3e4178271b4b7fe75a69c8f0665dbe275b41d7c3'


def source_model():
    return subprocess.check_output(
        ['git', 'show', SOURCE_MODEL + ':tools/qualify_host_codec_native.py'], cwd=ROOT)


def model():
    _, record, snapshot, native, materials = original_model()
    reader = object.__new__(owner.FrozenHostCodecFuncRefsProducts)
    reader.source = SOURCE_MODEL
    reader.controls, reader.recipe = owner.producer_contract(source_model())
    reader.stages = ('source-revision', 'rust-version', 'normal-host-build',
        *(stage + suffix for stage, _, _, _ in reader.controls for suffix in ('-list', '-run')))
    cargo = ['cargo', '--config', '/controlled/source/.cargo/managed-guest.toml']
    commands = [row['argv'] for row in record['commands'][:3]]
    for _, package, needle, _ in reader.controls:
        args = [*cargo, 'test', '--locked', '-p', package, '--lib', needle, '--']
        commands.extend([args + ['--list'], args + ['--test-threads=1']])
    record.update(sourceRevision=SOURCE_MODEL, controlCount=92,
        nativeCohort=owner.COHORT, scope=owner.SCOPE,
        controls={stage: list(cases) for stage, _, _, cases in reader.controls},
        commands=[{'stage': stage, 'argv': argv, 'exitCode': 0, 'seconds': .1,
            'logs': {stream: {'path': f'logs/{index:02d}-{stage}.{stream}.txt',
                'bytes': 0, 'sha256': 'sha256:' + '0' * 64} for stream in ('stdout', 'stderr')}}
            for index, (stage, argv) in enumerate(zip(reader.stages, commands))])
    return reader, record, snapshot, native, materials


class HostCodecFuncRefsProductsReaderControls(unittest.TestCase):
    def test_literal_v4_contract_requires_twenty_groups_all_ninety_two_and_original_prefix(self):
        raw = source_model()
        controls, recipe = owner.producer_contract(raw)
        previous, previous_recipe = table_store.producer_contract(table_store_source())
        self.assertEqual((len(controls), sum(len(row[3]) for row in controls), len(recipe)), (20, 92, 22))
        self.assertEqual(controls[:17], previous)
        self.assertEqual(recipe, previous_recipe)
        self.assertEqual(controls[-1], ('c-ready-handoff', 'latent-component-threading',
            'c_ready_handoff_', (
                'component::c::tests::c_ready_handoff_canonical_requires_ready_aware_promote',
                'component::c::tests::c_ready_handoff_final_graph_refuses_resume_or_mismatched_target')))
        scopes = [ast.literal_eval(value) for node in ast.walk(ast.parse(raw))
            if isinstance(node, ast.Dict) for key, value in zip(node.keys, node.values)
            if isinstance(key, ast.Constant) and key.value == 'scope']
        self.assertEqual(scopes, [owner.SCOPE])
        for invalid in (b'', raw + b'\nCONTROLS = ()\n',
                raw.replace(b"'tools/build_process_signals.py',", b'', 1),
                raw.replace(b"'c-ready-handoff'", b"'original-host-memory'", 1)):
            with self.subTest(size=len(invalid)), self.assertRaises(WorkflowError):
                owner.producer_contract(invalid)
        with self.assertRaises(WorkflowError):
            original.producer_contract(raw)
        with self.assertRaises(WorkflowError):
            table_store.producer_contract(raw)

    def test_v4_full_model_refuses_old_profiles_partial_or_reordered_commands_and_forged_success(self):
        reader, record, snapshot, native, materials = model()
        reader.validate_record(record, snapshot, native, materials)
        for kind in ('v1-cohort', 'v2-cohort', 'old-scope', 'old-count', 'count-bool',
                'missing-control', 'missing-command', 'extra-command', 'reordered',
                'failed-command', 'wrong-command', 'missing-stream', 'extra-time',
                'unqualified-flag', 'foreign-source'):
            bad = copy.deepcopy(record)
            if kind == 'v1-cohort': bad['nativeCohort'] = original.COHORT
            elif kind == 'v2-cohort': bad['nativeCohort'] = table_store.COHORT
            elif kind == 'old-scope': bad['scope'] = table_store.SCOPE
            elif kind == 'old-count': bad['controlCount'] = 81
            elif kind == 'count-bool': bad['controlCount'] = True
            elif kind == 'missing-control': del bad['controls']['c-ready-handoff']
            elif kind == 'missing-command': bad['commands'].pop()
            elif kind == 'extra-command': bad['commands'].append(bad['commands'][-1])
            elif kind == 'reordered': bad['commands'][-1], bad['commands'][-2] = bad['commands'][-2:]
            elif kind == 'failed-command': bad['commands'][-1]['exitCode'] = 1
            elif kind == 'wrong-command': bad['commands'][-1]['argv'][-1] = '--ignored'
            elif kind == 'missing-stream': del bad['commands'][-1]['logs']['stderr']
            elif kind == 'extra-time': bad['commands'][-1]['seconds'] = 1321
            elif kind == 'unqualified-flag': bad['signedQualification'] = True
            else: bad['sourceRevision'] = '0' * 40
            with self.subTest(kind=kind), self.assertRaises(WorkflowError):
                reader.validate_record(bad, snapshot, native, materials)
        for previous_model in (original_model, table_store_model):
            previous, old_record, old_snapshot, old_native, old_materials = previous_model()
            with self.assertRaises(WorkflowError):
                previous.validate_record(record, snapshot, native, materials)
            with self.assertRaises(WorkflowError):
                reader.validate_record(old_record, old_snapshot, old_native, old_materials)

    def test_old_defaults_and_shared_fixed_member_acquisition_remain_exact(self):
        for previous_model, counts in ((original_model, (61, 31)), (table_store_model, (81, 37))):
            reader, record, snapshot, native, materials = previous_model()
            reader.validate_record(record, snapshot, native, materials)
            self.assertEqual((reader.control_count, reader.command_count), counts)
        current = object.__new__(owner.FrozenHostCodecFuncRefsProducts)
        self.assertEqual(current._producer_origin(), (original.WORKFLOW,
            'Original ledger, actual codec table Store registry FuncRefs ownership '
            'and closed diagnostics', 'host-codec-memory-'))
        self.assertEqual((current.control_count, current.command_count), (92, 43))
        for name in ('prepare', 'verify_prepared', 'extract', 'preflight'):
            self.assertIs(getattr(owner.FrozenHostCodecFuncRefsProducts, name),
                getattr(fixed.FrozenNativeProducts, name))


if __name__ == '__main__':
    unittest.main()
