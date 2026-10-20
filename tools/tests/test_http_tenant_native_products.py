"""Pure source/archive controls; no native producer or component execution."""
import copy
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import http_tenant_native_products as native
from tools.phase2_operator_process import WorkflowError


class HttpTenantNativeProducts(unittest.TestCase):
    def test_direct_cli_bootstraps_repository_without_pythonpath_or_network(self):
        import os
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as temporary:
            completed = subprocess.run([sys.executable, '-B', str(Path(native.__file__)), '--help'],
                cwd=temporary, env={**os.environ, 'PYTHONPATH': ''},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
            self.assertEqual(completed.returncode, 0, completed.stderr.decode())
            self.assertIn(b'--output', completed.stdout)
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_unfrozen_pins_refuse_before_network_or_output(self):
        with patch.object(native, 'ARTIFACT', None), patch.object(native, 'api') as api:
            with self.assertRaisesRegex(WorkflowError, 'completed-producer-pins-required'):
                native._official_artifact()
            api.assert_not_called()

    def test_real_fixed_git_materials_bind_v7_and_all_three_auxiliary_trees(self):
        materials = native._git_materials()
        self.assertEqual(len(materials), 114)
        self.assertEqual(sum(row['bytes'] for row in materials.values()), 495787)
        self.assertEqual(materials['wit/host-abi-phase3-v7.json']['sha256'],
            'sha256:e4f5211dbb2ced0c32ad112ed8ca589df2e3f107149e20a588549157e680a7b0')
        for prefix in ('wit/', 'schemas/', 'examples/echo-contract/wit/'):
            self.assertTrue(any(name.startswith(prefix) for name in materials))
        self.assertEqual(materials, native._git_materials())

    def test_record_requires_every_owned_product_source_material_and_control(self):
        identity = {'sha256': 'sha256:'+'1'*64, 'bytes': 1}
        source = {'sha256': 'sha256:'+'2'*64, 'files': 1, 'bytes': 1}
        materials = {'wit/host-abi-phase3-v7.json': identity}
        snapshot = {'native': source, 'materials': materials}
        record = {'schemaVersion': 'latent.sdk.native-products.v1', 'status': 'built',
            'sourceRevision': native.SOURCE, 'source': source, 'materials': materials,
            'compiler': 'rustc 1.97.1 (fixed test compiler)',
            'products': {name: identity for name in native.PRODUCTS},
            'commands': [{'stage': stage, 'exitCode': 0, 'seconds': 1} for stage in native.STAGES],
            'profile': 'normal-managed-guest-default-features', 'signedQualification': False,
            'guestComponentsCompiled': False, 'historicalReceiptRewritten': False}
        native.validate_record(record, snapshot, source, materials)
        mutations = (
            lambda row: row.update(sourceRevision='a'*40),
            lambda row: row.update(source={'sha256': 'sha256:'+'3'*64}),
            lambda row: row['materials'].clear(),
            lambda row: row['products'].pop('latentd'),
            lambda row: row['products'].update(extra=identity),
            lambda row: row.update(signedQualification=True),
            lambda row: row.update(guestComponentsCompiled=True),
            lambda row: row.update(historicalReceiptRewritten=True),
            lambda row: row.update(profile='selected-or-privileged'),
            lambda row: row.update(rawPayload='unrecognized'),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                changed = copy.deepcopy(record);mutate(changed)
                with self.assertRaises(WorkflowError):
                    native.validate_record(changed, snapshot, source, materials)
        with self.assertRaises(WorkflowError):
            native.validate_record(record, {'native': source, 'materials': {}}, source, materials)
        self.assertEqual(set(native.native_products(Path('prepared'))),
            {'latent', 'latentd', 'package', 'capsule_contracts', 'capsule_authoring'})

    def test_command_failures_missing_observer_and_nonfinite_or_aggregate_times_refuse(self):
        identity = {'sha256': 'sha256:'+'1'*64, 'bytes': 1}
        source = {'sha256': 'sha256:'+'2'*64, 'files': 1, 'bytes': 1}
        snapshot = {'native': source, 'materials': {}}
        record = {'schemaVersion': 'latent.sdk.native-products.v1', 'status': 'built',
            'sourceRevision': native.SOURCE, 'source': source, 'materials': {},
            'compiler': 'rustc 1.97.1 (fixed test compiler)',
            'products': {name: identity for name in native.PRODUCTS},
            'commands': [{'stage': stage, 'exitCode': 0, 'seconds': 1} for stage in native.STAGES],
            'profile': 'normal-managed-guest-default-features', 'signedQualification': False,
            'guestComponentsCompiled': False, 'historicalReceiptRewritten': False}
        for value in (True, -1, float('nan'), float('inf'), 1321):
            changed = copy.deepcopy(record);changed['commands'][-1]['seconds'] = value
            with self.subTest(seconds=value), self.assertRaises(WorkflowError):
                native.validate_record(changed, snapshot, source, {})
        for change in ('missing', 'reorder', 'failed', 'boolean-code', 'aggregate'):
            changed = copy.deepcopy(record)
            if change == 'missing': changed['commands'].pop()
            if change == 'reorder': changed['commands'].reverse()
            if change == 'failed': changed['commands'][-1]['exitCode'] = 1
            if change == 'boolean-code': changed['commands'][-1]['exitCode'] = False
            if change == 'aggregate':
                for row in changed['commands']: row['seconds'] = 300
            with self.subTest(change=change), self.assertRaises(WorkflowError):
                native.validate_record(changed, snapshot, source, {})

    def test_fixed_member_preflight_rejects_missing_oversize_and_links(self):
        def archive(change=None):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as output:
                for name in native.ALLOWED:
                    if change == 'missing' and name == 'native-products.json': continue
                    info = zipfile.ZipInfo(name)
                    if change == 'link' and name == 'native-products.json':
                        info.create_system = 3;info.external_attr = 0o120777 << 16
                    output.writestr(info, b'x')
            stream.seek(0)
            return zipfile.ZipFile(stream)
        with archive() as value:
            self.assertEqual(set(native.preflight(value)), set(native.ALLOWED))
        for kind in ('missing', 'link'):
            with archive(kind) as value, self.subTest(kind=kind), self.assertRaises((WorkflowError, KeyError)):
                native.preflight(value)
        with archive() as value:
            value.getinfo('source-inputs.json').file_size = 1024**2+1
            with self.assertRaises(WorkflowError): native.preflight(value)

    def test_extract_refuses_nonallowlisted_traversal_before_any_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'not-created'
            for name in ('../secret', '/absolute', 'native-binaries/../latent',
                    'native-binaries\\latent', 'raw/private.txt'):
                with self.subTest(name=name), self.assertRaises(WorkflowError):
                    native.extract(None, name, output)
                self.assertFalse(output.exists())
