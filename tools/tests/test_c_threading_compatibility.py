"""Source/reader controls only; the native proof command is never executed."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools.c_guest import threading, threading_compatibility as supplement
from tools.dev_workflow.common import digest, encode
from tools.rust_capsule_project import read_file, write_json


class CThreadingCompatibility(unittest.TestCase):
    def setUp(self):
        owned = tempfile.TemporaryDirectory()
        self.addCleanup(owned.cleanup)
        self.root = Path(owned.name)
        self.output = self.root / 'output'
        self.output.mkdir()
        self.public = 'examples:thread/api@1.0.0#greet'
        self.component = b'controlled final component bytes'
        self.original = b'controlled original core'
        self.derived = b'controlled derived core'
        self.proof = {'originalCore': self.root / 'core', 'derivedCore': self.root / 'derived',
            'unboundComponent': self.root / 'unbound', 'derivation': self.root / 'derivation.json',
            'publicExport': self.public, 'finalComponent': self.root / 'final'}
        for name, value in (('originalCore', self.original), ('derivedCore', self.derived),
                            ('unboundComponent', b'controlled unbound'), ('finalComponent', self.component)):
            self.proof[name].write_bytes(value)
        (self.output / 'component.wasm').write_bytes(self.component)
        self.derivation = {'formatVersion': 1, 'profile': threading.PROFILE,
            'originalCoreDigest': digest(self.original), 'derivedCoreDigest': digest(self.derived),
            'publicExport': self.public, 'rootRecordBytes': 144,
            'canonicalComponentAuthenticated': False, 'standardRuntimeQualified': False}
        write_json(self.proof['derivation'], self.derivation)
        self.surface = {'imports': list(threading.IMPORTS), 'exports': [self.public.rsplit('#', 1)[0]]}
        self.host = supplement.base.host_manifest('lsf-host-abi-phase3-v5')
        self.inspection = {'componentDigest': digest(self.component), 'hostAbiProfile': self.host['id'],
            'hostAbiDigest': digest(encode(self.host)), 'imports': list(threading.IMPORTS), 'findings': [
                {'classification': 'unknown-import', 'phase': 'link', 'evidence': 'final-component',
                 'operation': supplement.PORT},
                {'classification': 'unresolved-behavior', 'phase': 'invocation', 'evidence': 'not-evaluated'}]}
        self.tool = self.root / 'unexecuted-tool'
        self.tool.write_bytes(b'controlled never executed binary')
        self.commands = Mock()
        self.commands.run.side_effect = lambda *args: args[-1].write_bytes(self.component)

    def invoke(self, *, profile=threading.PROFILE, proof='default'):
        def original_inspection(*args, **kwargs):
            write_json(self.output / 'compatibility-inspection.json', self.inspection)
            raise ValueError('final-component-compatibility-failed; inspect compatibility-inspection.json')
        with patch.object(supplement.base, 'inspect', side_effect=original_inspection):
            return supplement.inspect(self.commands, Path('unexecuted-wasm-tools'), self.output,
                self.surface, profile=profile, proof=self.proof if proof == 'default' else proof, transformer=self.tool)

    def test_supplement_preserves_blocked_base_and_binds_only_the_selected_profile(self):
        record = self.invoke()
        self.assertFalse(record['baseInspectionReclassified'])
        self.assertEqual(record['status'], 'source-profile-compatible-runtime-unqualified')
        self.assertIs(record['signedQualification'], False)
        self.assertEqual(record['authority'], 'none')
        self.assertEqual(record['baseInspection']['digest'],
                         digest(read_file(self.output / 'compatibility-inspection.json')))
        self.assertEqual(record['baseHostAbiDigest'], digest(encode(self.host)))
        self.assertEqual(record['supplementalPort']['sourceDigest'], supplement.WIT_DIGEST)
        self.assertEqual(self.commands.run.call_args.args[:3],
                         ('c-thread-compatibility-proof', self.tool, '--c-thread-bind-v1'))
        from tools import qualify_c_thread_runtime as qualification
        from tools.phase3_resource_identity import file_identity
        write_json(self.output / 'c-threading-derivation.json', self.derivation)
        write_json(self.output / 'compatibility-report.json', {'status': 'blocked'})
        assets = ((supplement.NAME, supplement.MEDIA),
            ('compatibility-inspection.json', 'application/vnd.latent.guest.compatibility.inspection.v1+json'),
            ('compatibility-report.json', 'application/vnd.latent.guest.compatibility.v1+json'))
        layers = [{'path': name, 'source': name, 'role': 'asset', 'mediaType': media}
                  for name, media in assets]
        write_json(self.output / 'package-source.json', {'layers': layers})
        component = file_identity(self.output / 'component.wasm')
        evidence = qualification.supplement_evidence(self.output, component, self.derivation)
        self.assertEqual(set(evidence), {name for name, _ in assets})
        layers[0]['mediaType'] = 'application/foreign'
        (self.output / 'package-source.json').write_bytes(encode({'layers': layers}))
        with self.assertRaisesRegex(RuntimeError, 'package-assets'):
            qualification.supplement_evidence(self.output, component, self.derivation)

    def test_no_selection_rust_profile_and_incomplete_proof_refuse_before_verifier(self):
        for profile in (None, False, 'single-threaded', 'rust-context40-sole-consumer-one-task-start-v1'):
            with self.subTest(profile=profile), self.assertRaises(Exception):
                self.invoke(profile=profile)
        for missing in self.proof:
            changed = dict(self.proof); changed.pop(missing)
            with self.subTest(missing=missing), self.assertRaises(Exception):
                self.invoke(proof=changed)
        for changed in (None, {}, False, dict(self.proof, extra='unreviewed')):
            with self.subTest(proof=changed), self.assertRaises(Exception):
                self.invoke(proof=changed)
        self.commands.run.assert_not_called()

    def test_stale_component_surface_derivation_or_other_unknown_import_cannot_be_supplemented(self):
        for kind in ('component', 'surface', 'derivation', 'unknown', 'base-digest'):
            with self.subTest(kind=kind):
                if kind == 'component': (self.output / 'component.wasm').write_bytes(b'foreign component')
                elif kind == 'surface': self.surface['exports'] = ['foreign:export/api@1.0.0']
                elif kind == 'derivation':
                    changed = dict(self.derivation, originalCoreDigest=digest(b'foreign'))
                    self.proof['derivation'].write_bytes(encode(changed))
                elif kind == 'unknown': self.inspection['findings'][0]['operation'] = 'foreign:port/api@1.0.0'
                else: self.inspection['hostAbiDigest'] = digest(b'foreign ABI')
                inspection = self.output / 'compatibility-inspection.json'
                if inspection.exists(): inspection.unlink()
                reason = {'component': 'exact-final-component', 'surface': 'selected-surface',
                    'derivation': 'original-derivation', 'unknown': 'only-one-closed-supplemental-port',
                    'base-digest': 'only-one-closed-supplemental-port'}[kind]
                with self.assertRaisesRegex(Exception, reason): self.invoke()
                (self.output / 'component.wasm').write_bytes(self.component)
                self.surface['exports'] = [self.public.rsplit('#', 1)[0]]
                self.proof['derivation'].write_bytes(encode(self.derivation))
                self.inspection['findings'][0]['operation'] = supplement.PORT
                self.inspection['hostAbiDigest'] = digest(encode(self.host))
        self.commands.run.assert_not_called()

    def test_full_recomputed_component_mismatch_refuses_without_a_supplement(self):
        self.commands.run.side_effect = lambda *args: args[-1].write_bytes(b'foreign recomputed component')
        with self.assertRaisesRegex(Exception, 'full-recomputed-component-proof'): self.invoke()
        self.assertFalse((self.output / supplement.NAME).exists())

    def test_changed_port_wit_and_real_verifier_refusal_cannot_produce_a_supplement(self):
        original = supplement.read_file
        def changed(path, *args):
            return b'foreign port declaration' if path == supplement.ROOT / supplement.WIT else original(path, *args)
        with patch.object(supplement, 'read_file', side_effect=changed), \
                self.assertRaisesRegex(Exception, 'exact-native-port-wit'):
            self.invoke()
        self.assertFalse((self.output / supplement.NAME).exists())
        (self.output / 'compatibility-inspection.json').unlink()
        (self.output / 'c-threading-compatibility-verified.wasm').unlink()
        failure = RuntimeError('controlled native verifier refusal')
        self.commands.run.side_effect = failure
        with self.assertRaises(RuntimeError) as seen:
            self.invoke()
        self.assertIs(seen.exception, failure)
        self.assertFalse((self.output / supplement.NAME).exists())


if __name__ == '__main__':
    unittest.main()
