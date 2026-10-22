"""Schema/refusal models only; no new producer or guest qualification."""
import copy
import subprocess
import unittest

from tools import host_codec_native_products_reader as owner
from tools import sdk_native_products_reader as original
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT

SOURCE = '7b6365ee39dea9770591a931b96711965f8a1aaf'


def contract():
    return owner.producer_contract(subprocess.check_output(
        ['git', 'show', SOURCE + ':tools/qualify_host_codec_native.py'], cwd=ROOT))


def model():
    """A complete reader model, explicitly not an observed successful origin."""
    controls, recipe = contract()
    reader = object.__new__(owner.FrozenHostCodecProducts)
    reader.source, reader.controls, reader.recipe = SOURCE, controls, recipe
    reader.stages = ('source-revision', 'rust-version', 'normal-host-build',
        *(stage + suffix for stage, _, _, _ in controls for suffix in ('-list', '-run')))
    cargo = ['cargo', '--config', '/controlled/source/.cargo/managed-guest.toml']
    commands = [['git', 'rev-parse', 'HEAD'], ['rustc', '--version'],
        [*cargo, 'build', '--locked', '-p', 'latent', '-p', 'latentd', '--bins',
            '-p', 'latent-packaging', '--example', 'package', '--example', 'capsule_contracts',
            '-p', 'latent-policy', '--example', 'capsule_authoring']]
    for _, package, needle, _ in controls:
        args = [*cargo, 'test', '--locked', '-p', package, '--lib', needle, '--']
        commands.extend([args + ['--list'], args + ['--test-threads=1']])
    identity = {'sha256': 'sha256:' + '1' * 64, 'bytes': 1}
    native, materials = {'controlled': 'model-not-native-evidence'}, {'controlled/model': identity}
    rows = []
    for index, (stage, argv) in enumerate(zip(reader.stages, commands)):
        rows.append({'stage': stage, 'exitCode': 0, 'seconds': .1, 'argv': argv,
            'logs': {stream: {'path': f'logs/{index:02d}-{stage}.{stream}.txt',
                'bytes': 0, 'sha256': 'sha256:' + '0' * 64} for stream in ('stdout', 'stderr')}})
    record = {'schemaVersion': 'latent.host-codec.native-products.v1', 'status': 'passed',
        'sourceRevision': SOURCE, 'source': native, 'materials': materials, 'compiler': 'rustc 1.97.1 (model)',
        'products': {name: identity.copy() for name in owner.PRODUCTS}, 'commands': rows,
        'controlCount': 61, 'nativeCohort': owner.COHORT,
        'controls': {stage: list(cases) for stage, _, _, cases in controls},
        'profile': 'normal-managed-guest-default-features', 'signedQualification': False,
        'guestJavaScriptEngineCompiled': False, 'guestSourceCompiled': False,
        'historicalReceiptRewritten': False, 'scope': owner.SCOPE}
    return reader, record, {'native': native, 'materials': materials}, native, materials


class HostCodecProductsReaderControls(unittest.TestCase):
    def test_literal_frozen_contract_requires_full_recipe_and_all_sixty_one_names(self):
        raw = subprocess.check_output(['git', 'show', SOURCE + ':tools/qualify_host_codec_native.py'], cwd=ROOT)
        controls, recipe = owner.producer_contract(raw)
        self.assertEqual(len(controls), 14)
        self.assertEqual(sum(len(cases) for _, _, _, cases in controls), 61)
        self.assertEqual(len(recipe), 22)
        for invalid in (b'', raw + b'\nCONTROLS = ()\n',
                raw.replace(b"'original-host-memory'", b"'result-owner'", 1),
                raw.replace(b"'tools/build_process_signals.py',", b'', 1),
                raw.replace(b"'examples/capsule_contracts'", b"'examples/unknown'", 1)):
            with self.subTest(size=len(invalid)), self.assertRaises(WorkflowError):
                owner.producer_contract(invalid)

    def test_full_model_rejects_partial_foreign_failed_or_relabelled_producer_records(self):
        reader, record, snapshot, native, materials = model()
        reader.validate_record(record, snapshot, native, materials)
        for kind in ('partial', 'failed', 'source', 'schema', 'cohort', 'guest', 'count-bool',
                'control-name', 'missing-product', 'command-duplicate', 'command-order', 'exit-bool',
                'exit-failed', 'unlocked', 'foreign-package', 'config', 'nonfinite', 'log-path',
                'log-size-bool', 'log-overflow', 'missing-stream', 'time-bound', 'extra-field'):
            bad = copy.deepcopy(record)
            if kind == 'partial': bad['commands'].pop()
            elif kind == 'failed': bad['status'] = 'failed'
            elif kind == 'source': bad['sourceRevision'] = '0' * 40
            elif kind == 'schema': bad['schemaVersion'] = 'latent.sdk.native-products.v1'
            elif kind == 'cohort': bad['nativeCohort'] = 'original-upstream-only'
            elif kind == 'guest': bad['signedQualification'] = True
            elif kind == 'count-bool': bad['controlCount'] = True
            elif kind == 'control-name': bad['controls']['original-host-memory'][0] = 'unknown'
            elif kind == 'missing-product': del bad['products']['latentd']
            elif kind == 'command-duplicate': bad['commands'][4] = bad['commands'][3]
            elif kind == 'command-order': bad['commands'][3], bad['commands'][4] = bad['commands'][4], bad['commands'][3]
            elif kind == 'exit-bool': bad['commands'][0]['exitCode'] = False
            elif kind == 'exit-failed': bad['commands'][0]['exitCode'] = 1
            elif kind == 'unlocked': bad['commands'][2]['argv'].remove('--locked')
            elif kind == 'foreign-package': bad['commands'][3]['argv'][6] = 'latent-unknown'
            elif kind == 'config': bad['commands'][2]['argv'][2] = '/source/../other/.cargo/managed-guest.toml'
            elif kind == 'nonfinite': bad['commands'][0]['seconds'] = float('nan')
            elif kind == 'time-bound': bad['commands'][0]['seconds'] = 1320
            elif kind == 'log-path': bad['commands'][0]['logs']['stdout']['path'] = '../outside'
            elif kind == 'log-size-bool': bad['commands'][0]['logs']['stdout']['bytes'] = False
            elif kind == 'log-overflow': bad['commands'][0]['logs']['stdout']['bytes'] = 4 * 1024**2 + 1
            elif kind == 'missing-stream': del bad['commands'][0]['logs']['stderr']
            else: bad['unobservedQualification'] = True
            with self.subTest(kind=kind), self.assertRaises(WorkflowError):
                reader.validate_record(bad, snapshot, native, materials)

    def test_original_factory_defaults_and_fixed_member_algorithm_remain_selected(self):
        ordinary = object.__new__(original.FrozenNativeProducts)
        self.assertEqual(ordinary._material_recipe(), original.MATERIALS)
        self.assertEqual(ordinary._producer_origin(), (original.WORKFLOW,
            'Build and retain five source-bound native products', 'sdk-native-products-'))
        self.assertIs(owner.FrozenHostCodecProducts.prepare, original.FrozenNativeProducts.prepare)
        self.assertIs(owner.FrozenHostCodecProducts.verify_prepared, original.FrozenNativeProducts.verify_prepared)
        self.assertIs(owner.FrozenHostCodecProducts.extract, original.FrozenNativeProducts.extract)
        self.assertIs(owner.FrozenHostCodecProducts.preflight, original.FrozenNativeProducts.preflight)


if __name__ == '__main__':
    unittest.main()
