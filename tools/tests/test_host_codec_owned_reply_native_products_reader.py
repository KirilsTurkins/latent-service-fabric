"""Closed v9 schema models; no download, product execution or native build."""
import ast
import copy
import subprocess
import unittest

from tools import host_codec_owned_reply_native_products_reader as owner
from tools import host_codec_native_products_reader as previous
from tools import sdk_native_products_reader as original
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT
from tools.tests.test_host_codec_native_products_reader import model as previous_model

SOURCE = 'cb8ceefc5f6343301871dbde1d8a853d3581cc30'
PREVIOUS_SOURCE = '4ed0db7f07245732d07f867e95ec008a804485e5'


def source_model(source=SOURCE):
    return subprocess.check_output(['git', 'show', source + ':tools/qualify_host_codec_native.py'], cwd=ROOT)


def contract_model(controls, recipe):
    return ('PRODUCTS = ' + repr(original.PRODUCTS) + '\nCONTROLS = ' + repr(controls)
        + '\nRECIPE = ' + repr(recipe) + '\n').encode()


def model():
    _, record, snapshot, native, materials = previous_model()
    reader = object.__new__(owner.FrozenHostCodecOwnedReplyProducts)
    reader.source = SOURCE
    reader.controls, reader.recipe = owner.producer_contract(source_model())
    reader.stages = ('source-revision', 'rust-version', 'normal-host-build',
        *(stage + suffix for stage, _, _, _ in reader.controls for suffix in ('-list', '-run')))
    cargo = ['cargo', '--config', '/controlled/source/.cargo/managed-guest.toml']
    commands = [row['argv'] for row in record['commands'][:3]]
    for _, package, needle, _ in reader.controls:
        args = [*cargo, 'test', '--locked', '-p', package, '--lib', needle, '--']
        commands.extend([args + ['--list'], args + ['--test-threads=1']])
    record.update(sourceRevision=SOURCE, controlCount=128,
        nativeCohort=owner.COHORT, scope=owner.SCOPE,
        controls={stage: list(cases) for stage, _, _, cases in reader.controls},
        commands=[{'stage': stage, 'argv': argv, 'exitCode': 0, 'seconds': .1,
            'logs': {stream: {'path': f'logs/{index:02d}-{stage}.{stream}.txt',
                'bytes': 0, 'sha256': 'sha256:' + '0' * 64} for stream in ('stdout', 'stderr')}}
            for index, (stage, argv) in enumerate(zip(reader.stages, commands))])
    return reader, record, snapshot, native, materials


class HostCodecOwnedReplyNativeProductsReader(unittest.TestCase):
    def test_exact128_retains121_prefix_recipe_and_only_the_closed_latent_cli_group(self):
        raw = source_model()
        controls, recipe = owner.producer_contract(raw)
        old, old_recipe = previous._producer_contract(source_model(PREVIOUS_SOURCE), 26, 121)
        self.assertEqual((len(controls), sum(len(row[3]) for row in controls), len(recipe)), (28, 128, 22))
        self.assertEqual(controls[:26], old)
        self.assertEqual(recipe, old_recipe)
        self.assertNotIn('tools/host_codec_native_products_reader.py', recipe)
        self.assertEqual(tuple(len(row[3]) for row in controls[-2:]), (5, 2))
        self.assertEqual(controls[-1], owner.CLI_CONTROL)
        scopes = [ast.literal_eval(value) for node in ast.walk(ast.parse(raw))
            if isinstance(node, ast.Dict) for key, value in zip(node.keys, node.values)
            if isinstance(key, ast.Constant) and key.value == 'scope']
        self.assertEqual(scopes, [owner.SCOPE])
        # The old/default parser still rejects package latent, even at the new
        # counts. Only the exact explicit new group can use this closed seam.
        with self.assertRaises(WorkflowError):
            previous._producer_contract(raw, 28, 128)
        for index, value in ((0, 'foreign-cli-stage'), (1, 'latent-foreign'),
                (2, 'foreign_'), (3, owner.CLI_CONTROL[3][:-1]),
                (3, (owner.CLI_CONTROL[3][0], owner.CLI_CONTROL[3][0] + '_foreign'))):
            changed = list(controls)
            row = list(changed[-1]); row[index] = value; changed[-1] = tuple(row)
            with self.subTest(index=index, value=value), self.assertRaises(WorkflowError):
                owner.producer_contract(contract_model(tuple(changed), recipe))
        foreign = list(controls)
        row = list(foreign[0]); row[1] = 'latent'; foreign[0] = tuple(row)
        with self.assertRaises(WorkflowError):
            owner.producer_contract(contract_model(tuple(foreign), recipe))
        for invalid in (b'', raw + b'\nCONTROLS = ()\n',
                contract_model(controls, recipe[:-1]), source_model(PREVIOUS_SOURCE)):
            with self.assertRaises(WorkflowError):
                owner.producer_contract(invalid)

    def test_full128_model_refuses_foreign_source_materials_partial_or_reordered_commands(self):
        reader, record, snapshot, native, materials = model()
        reader.validate_record(record, snapshot, native, materials)
        for kind in ('source', 'native', 'materials', 'old-cohort', 'scope', 'count-bool',
                'missing-control', 'missing-product', 'missing-command', 'extra-command',
                'reordered', 'failed', 'wrong-argv', 'missing-stream', 'excess-time', 'guest-claim'):
            bad = copy.deepcopy(record)
            if kind == 'source': bad['sourceRevision'] = PREVIOUS_SOURCE
            elif kind == 'native': bad['source'] = {}
            elif kind == 'materials': bad['materials'] = {}
            elif kind == 'old-cohort': bad['nativeCohort'] = previous.COHORT
            elif kind == 'scope': bad['scope'] += '-broadened'
            elif kind == 'count-bool': bad['controlCount'] = True
            elif kind == 'missing-control': bad['controls'].pop(reader.controls[-1][0])
            elif kind == 'missing-product': bad['products'].pop('latentd')
            elif kind == 'missing-command': bad['commands'].pop()
            elif kind == 'extra-command': bad['commands'].append(bad['commands'][-1])
            elif kind == 'reordered': bad['commands'][-1], bad['commands'][-2] = bad['commands'][-2], bad['commands'][-1]
            elif kind == 'failed': bad['commands'][-1]['exitCode'] = 1
            elif kind == 'wrong-argv': bad['commands'][-1]['argv'][-1] = '--ignored'
            elif kind == 'missing-stream': bad['commands'][-1]['logs'].pop('stderr')
            elif kind == 'excess-time': bad['commands'][-1]['seconds'] = 1321
            else: bad['signedQualification'] = True
            with self.subTest(kind=kind), self.assertRaises(WorkflowError):
                reader.validate_record(bad, snapshot, native, materials)
        old, old_record, old_snapshot, old_native, old_materials = previous_model()
        old.validate_record(old_record, old_snapshot, old_native, old_materials)
        with self.assertRaises(WorkflowError):
            old.validate_record(record, snapshot, native, materials)
        with self.assertRaises(WorkflowError):
            reader.validate_record(old_record, old_snapshot, old_native, old_materials)

    def test_new_schema_inherits_original_acquisition_and_cannot_select_a_tuple(self):
        self.assertEqual((owner.FrozenHostCodecOwnedReplyProducts.control_count,
            owner.FrozenHostCodecOwnedReplyProducts.command_count), (128, 59))
        self.assertEqual(owner.FrozenHostCodecOwnedReplyProducts.job_name,
            'Original ledger closed context replies and runtime memory ownership diagnostics')
        for name in ('prepare', 'verify_prepared', 'extract', 'preflight'):
            self.assertIs(getattr(owner.FrozenHostCodecOwnedReplyProducts, name),
                getattr(original.FrozenNativeProducts, name))
        for name in ('SOURCE', 'RUN', 'ARTIFACT', 'prepare', 'native_products'):
            self.assertFalse(hasattr(owner, name))


if __name__ == '__main__':
    unittest.main()
