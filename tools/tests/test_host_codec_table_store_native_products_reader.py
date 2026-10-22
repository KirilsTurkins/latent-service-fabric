"""Closed schema models only; the literal failed source is not a product result."""
import copy
import subprocess
import unittest

from tools import host_codec_native_products_reader as original
from tools import host_codec_table_store_native_products_reader as owner
from tools import sdk_native_products_reader as fixed
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT
from tools.tests.test_host_codec_native_products_reader import model as original_model

SOURCE_MODEL = '050b9e71ba04a4bdc559f4a7fa48d6bd94c2ff38'


def source_model():
    return subprocess.check_output(
        ['git', 'show', SOURCE_MODEL + ':tools/qualify_host_codec_native.py'], cwd=ROOT)


def model():
    _, record, snapshot, native, materials = original_model()
    reader = object.__new__(owner.FrozenHostCodecTableStoreProducts)
    reader.source = SOURCE_MODEL
    reader.controls, reader.recipe = owner.producer_contract(source_model())
    reader.stages = ('source-revision', 'rust-version', 'normal-host-build',
        *(stage + suffix for stage, _, _, _ in reader.controls for suffix in ('-list', '-run')))
    cargo = ['cargo', '--config', '/controlled/source/.cargo/managed-guest.toml']
    commands = [row['argv'] for row in record['commands'][:3]]
    for _, package, needle, _ in reader.controls:
        args = [*cargo, 'test', '--locked', '-p', package, '--lib', needle, '--']
        commands.extend([args + ['--list'], args + ['--test-threads=1']])
    record.update(sourceRevision=SOURCE_MODEL, controlCount=81,
        nativeCohort=owner.COHORT, scope=owner.SCOPE,
        controls={stage: list(cases) for stage, _, _, cases in reader.controls},
        commands=[{'stage': stage, 'argv': argv, 'exitCode': 0, 'seconds': .1,
            'logs': {stream: {'path': f'logs/{index:02d}-{stage}.{stream}.txt',
                'bytes': 0, 'sha256': 'sha256:' + '0' * 64} for stream in ('stdout', 'stderr')}}
            for index, (stage, argv) in enumerate(zip(reader.stages, commands))])
    return reader, record, snapshot, native, materials


class HostCodecTableStoreProductsReaderControls(unittest.TestCase):
    def test_literal_v2_contract_requires_seventeen_groups_all_eighty_one_and_original_prefix(self):
        raw = source_model()
        controls, recipe = owner.producer_contract(raw)
        previous, previous_recipe = original.producer_contract(subprocess.check_output(
            ['git', 'show', '7b6365ee39dea9770591a931b96711965f8a1aaf:tools/qualify_host_codec_native.py'],
            cwd=ROOT))
        self.assertEqual((len(controls), sum(len(row[3]) for row in controls), len(recipe)), (17, 81, 22))
        self.assertEqual(controls[:14], previous)
        self.assertEqual(recipe, previous_recipe)
        for invalid in (b'', raw + b'\nCONTROLS = ()\n',
                raw.replace(b"'tools/build_process_signals.py',", b'', 1),
                raw.replace(b"'actual-native-table-owner'", b"'original-host-memory'", 1)):
            with self.subTest(size=len(invalid)), self.assertRaises(WorkflowError):
                owner.producer_contract(invalid)
        with self.assertRaises(WorkflowError):
            original.producer_contract(raw)

    def test_v2_full_model_refuses_old_cohort_partial_controls_commands_and_false_qualification(self):
        reader, record, snapshot, native, materials = model()
        reader.validate_record(record, snapshot, native, materials)
        for kind in ('old-cohort', 'old-scope', 'old-count', 'count-bool', 'missing-control',
                'missing-command', 'extra-command', 'reordered', 'unqualified-flag', 'foreign-source'):
            bad = copy.deepcopy(record)
            if kind == 'old-cohort': bad['nativeCohort'] = original.COHORT
            elif kind == 'old-scope': bad['scope'] = original.SCOPE
            elif kind == 'old-count': bad['controlCount'] = 61
            elif kind == 'count-bool': bad['controlCount'] = True
            elif kind == 'missing-control': del bad['controls']['closed-guest-trap-diagnostics']
            elif kind == 'missing-command': bad['commands'].pop()
            elif kind == 'extra-command': bad['commands'].append(bad['commands'][-1])
            elif kind == 'reordered': bad['commands'][-1], bad['commands'][-2] = bad['commands'][-2:]
            elif kind == 'unqualified-flag': bad['signedQualification'] = True
            else: bad['sourceRevision'] = '0' * 40
            with self.subTest(kind=kind), self.assertRaises(WorkflowError):
                reader.validate_record(bad, snapshot, native, materials)
        old_reader, old_record, old_snapshot, old_native, old_materials = original_model()
        with self.assertRaises(WorkflowError):
            old_reader.validate_record(record, snapshot, native, materials)
        with self.assertRaises(WorkflowError):
            reader.validate_record(old_record, old_snapshot, old_native, old_materials)

    def test_v1_defaults_and_shared_acquisition_algorithm_remain_exact(self):
        reader, record, snapshot, native, materials = original_model()
        reader.validate_record(record, snapshot, native, materials)
        self.assertEqual(reader._producer_origin(), (original.WORKFLOW,
            'Original ledger, actual codec and backend result ownership', 'host-codec-memory-'))
        self.assertEqual((reader.control_count, reader.command_count), (61, 31))
        current = object.__new__(owner.FrozenHostCodecTableStoreProducts)
        self.assertEqual(current._producer_origin(), (original.WORKFLOW,
            'Original ledger, actual codec table Store ownership and closed diagnostics', 'host-codec-memory-'))
        for name in ('prepare', 'verify_prepared', 'extract', 'preflight'):
            self.assertIs(getattr(owner.FrozenHostCodecTableStoreProducts, name),
                getattr(fixed.FrozenNativeProducts, name))


if __name__ == '__main__':
    unittest.main()
