"""Adverse closed-origin models; no download, host execution or guest claim."""
import copy
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

from tools import audit_memory_native_products as owner
from tools import sdk_native_products_reader as historical
from tools.phase2_operator_process import WorkflowError


def model():
    native = copy.deepcopy(owner.SOURCE_IDENTITY)
    materials = {f'fixed/{index}': {'sha256': 'sha256:' + '0' * 64, 'bytes': 1} for index in range(158)}
    snapshot = {'source': native, 'materials': materials}
    cargo = ['cargo', '--config', '/home/runner/work/latent-service-fabric/latent-service-fabric/.cargo/managed-guest.toml']
    test = cargo + ['test', '--locked', '-p', 'latent-audit', '--lib', owner.CONTROL, '--', '--exact']
    argv = (['git', 'rev-parse', 'HEAD'], ['rustc', '--version'], test + ['--list'],
            test + ['--test-threads=1'], cargo + ['build', '--locked', '-p', 'latent', '-p', 'latentd'])
    outcomes = []
    for label, records, providers in zip(owner.CASES, (2, 2, 1024, 4096, 16384), (False, True, True, True, True)):
        row = {'label': label, 'records': records, 'providers': providers, 'status': 'passed'}
        if records == 16384:
            row.update(exitCode=1, refusal={'status': 'observed',
                'report': {'terminalFailure': {'owner': 'platform', 'reason': 'resource-exhausted'}}})
        else:
            row.update(shutdown={'reaped': True, 'record': {'clean': True, 'report': {'clean': True}}},
                ready={'data': {'inventory': {'health': {'ready': True}}}}, auditQuery={'data': {'records': []}})
        outcomes.append(row)
    record = {'schemaVersion': 'latent.audit.node-startup.v1', 'status': 'passed',
        'sourceRevision': owner.SOURCE, 'inputs': snapshot, 'products': copy.deepcopy(owner.PRODUCTS),
        'controls': [owner.CONTROL], 'productionStartupObserved': True,
        'commands': [{'stage': stage, 'argv': args, 'exitCode': 0} for stage, args in zip(owner.STAGES, argv)],
        'outcomes': outcomes, 'signedGuestQualification': False, 'guestSourceCompiled': False,
        'historical193ProductsRebuilt': False, 'fullAllocationClosureQualified': False}
    return record, snapshot, native, materials


class ArchiveModel:
    def __init__(self):
        self.rows = {name: zipfile.ZipInfo(name) for name in owner.MEMBERS}
        for name, identity in owner.RECEIPTS.items():
            self.rows[name].file_size = identity['bytes']
        for name, identity in owner.PRODUCTS.items():
            self.rows['native-binaries/' + name].file_size = identity['bytes']

    def namelist(self):
        return list(self.rows)

    def getinfo(self, name):
        return self.rows[name]


class AuditMemoryNativeProductsTests(unittest.TestCase):
    def test_only_literal_completed_two_host_origin_and_five_stages_can_be_constructed(self):
        self.assertEqual(set(owner.native_products(Path('fixed'))), {'latent', 'latentd'})
        self.assertFalse(owner.READER._valid_stages(owner.STAGES[:-1]))
        self.assertFalse(owner.READER._valid_stages(tuple(reversed(owner.STAGES))))
        self.assertFalse(owner.READER._valid_stages(owner.STAGES + ('foreign',)))
        self.assertFalse(historical.FrozenNativeProducts._valid_stages(None, ('stage',) * 65))
        with self.assertRaises(TypeError):
            owner._FrozenAuditHosts(source='0' * 40)
        for attribute, changed in (('source', '0' * 40), ('run', owner.RUN + 1), ('job', owner.JOB + 1),
                                    ('event', 'workflow_dispatch'), ('branch', 'foreign')):
            reader = owner._FrozenAuditHosts()
            setattr(reader, attribute, changed)
            with self.subTest(attribute=attribute), self.assertRaises(WorkflowError):
                reader._pins()

    def test_closed_archive_refuses_foreign_missing_linked_or_oversized_material_before_extract(self):
        owner.READER.preflight(ArchiveModel())
        for mutation in ('extra', 'missing', 'symlink', 'oversized'):
            archive = ArchiveModel()
            name = 'native-binaries/latent'
            if mutation == 'extra':
                archive.rows['../foreign'] = zipfile.ZipInfo('../foreign')
            elif mutation == 'missing':
                archive.rows.pop(name)
            elif mutation == 'symlink':
                archive.rows[name].external_attr = (stat.S_IFLNK | 0o777) << 16
            else:
                archive.rows[name].file_size = owner.PRODUCT_LIMITS['latent'] + 1
            with self.subTest(mutation=mutation), self.assertRaises(WorkflowError):
                owner.READER.preflight(archive)
        with tempfile.TemporaryDirectory() as temporary, self.assertRaises(WorkflowError):
            owner.READER.extract(ArchiveModel(), '../foreign', Path(temporary) / 'foreign')

    def test_bound_record_rejects_missing_node_build_foreign_product_policy_and_unreaped_outcomes(self):
        record, snapshot, native, materials = model()
        owner.READER.validate_record(record, snapshot, native, materials)
        mutations = []
        value = copy.deepcopy(record);value['commands'][-1]['argv'] = value['commands'][-1]['argv'][:-2];mutations.append(value)
        value = copy.deepcopy(record);value['products']['latentd']['sha256'] = 'sha256:' + '0' * 64;mutations.append(value)
        value = copy.deepcopy(record);value['sourceRevision'] = '0' * 40;mutations.append(value)
        value = copy.deepcopy(record);value['outcomes'][2]['records'] = 4096;mutations.append(value)
        value = copy.deepcopy(record);value['outcomes'][0]['shutdown']['reaped'] = False;mutations.append(value)
        value = copy.deepcopy(record);value['outcomes'][-1]['exitCode'] = 0;mutations.append(value)
        value = copy.deepcopy(record);value['signedGuestQualification'] = True;mutations.append(value)
        for value in mutations:
            with self.assertRaises(WorkflowError):
                owner.READER.validate_record(value, snapshot, native, materials)

    def test_changed_receipt_is_rejected_before_any_product_is_selected(self):
        with tempfile.TemporaryDirectory() as temporary:
            prepared = Path(temporary)
            (prepared / 'receipt.json').write_bytes(b'{}')
            with self.assertRaisesRegex(WorkflowError, 'receipt-preimage'):
                owner.verify_prepared(prepared)
            self.assertFalse((prepared / 'native-binaries').exists())


if __name__ == '__main__':
    unittest.main()
