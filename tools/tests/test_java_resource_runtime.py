"""Source/resource ownership controls; emitted-component evidence is separate."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import guest_resources
from tools.build_snapshot import canonical, digest
from tools.java_guest import resources
from tools.java_guest.compiler import sdk_snapshot, stage_sdk_service
from tools.rust_capsule_project import ROOT, inventory


class JavaResourceRuntime(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = self.root / 'immutable'; self.data.mkdir()
        self.project = self.root / 'project'; self.project.mkdir()
        (self.project / 'build.gradle').write_bytes(b'// selected SDK recipe\n')
        self.sdk = ROOT / 'sdk/java-guest'

    def put(self, name, data):
        path = self.data / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def test_every_raw_name_survives_without_project_snapshot_exclusions(self):
        files = {'target/value': b'\x00\xff\n', '.git/value': b'opaque',
                 'dependency-inputs/value': b'', 'outside/Container$Nested.bin': b'nested',
                 'data/\u96ea.bin': b'utf8-name'}
        for name, data in files.items(): self.put(name, data)
        self.assertEqual(resources.source_inputs(self.data), files)

    def test_logical_aliases_and_fixed_count_and_byte_bounds_remain_closed(self):
        self.put('data/name', b'one')
        with patch.object(guest_resources, 'MAX_TOTAL', 2):
            with self.assertRaisesRegex(ValueError, 'byte or count limit'):
                resources.source_inputs(self.data)
        with patch.object(guest_resources, 'MAX_COUNT', 0):
            with self.assertRaisesRegex(ValueError, 'entry limit'):
                resources.source_inputs(self.data)
        manifest = {'schemaVersion': guest_resources.PROFILE, 'resources': [
            {'path': 'data/name', 'source': 'one', 'mediaType': 'application/octet-stream'},
            {'path': 'data/NAME', 'source': 'two', 'mediaType': 'application/octet-stream'}]}
        files = {guest_resources.MANIFEST: canonical(manifest), 'one': b'one', 'two': b'two'}
        with self.assertRaisesRegex(ValueError, 'collision'):
            resources.materialize(files, inventory(files), (), self.root / 'denied-alias')

    def test_materialization_uses_actual_common_manifest_bytes_and_binds_selection(self):
        manifest = {'schemaVersion': guest_resources.PROFILE, 'resources': [
            {'path': 'outside/badge.txt', 'source': 'data/badge.bin', 'mediaType': 'application/octet-stream'},
            {'path': 'target/empty', 'source': 'data/empty.bin', 'mediaType': 'application/octet-stream'}]}
        files = {guest_resources.MANIFEST: canonical(manifest), 'data/badge.bin': b'\x00private\xff\n',
                 'data/empty.bin': b''}
        output = self.root / 'selected'
        self.assertEqual(resources.materialize(files, inventory(files), (), output), output)
        self.assertEqual(resources.source_inputs(output), {'outside/badge.txt': files['data/badge.bin'], 'target/empty': b''})
        self.assertEqual(files['data/badge.bin'], b'\x00private\xff\n')

    def test_missing_dependency_owner_or_changed_bytes_cannot_enter_compiler_directory(self):
        row = {'path': 'outside/badge', 'source': 'data/badge', 'digest': digest(b'original'),
               'owner': 'outside:resource:1', 'mediaType': 'application/octet-stream'}
        for files in ({'data/badge': b'original'}, {'data/badge': b'changed',
                'latent.dependencies.lock.json': canonical({'artifacts': [{'id': row['owner'],
                    'files': [{'digest': row['digest'], 'size': len(b'original')}]}]})}):
            output = self.root / 'not-created'
            with self.assertRaises(ValueError):
                resources.materialize(files, inventory(files), (row,), output)
            self.assertFalse(output.exists())

    def test_empty_selection_and_no_manifest_have_distinct_valid_ownership(self):
        self.assertIsNone(resources.materialize({}, inventory({}), (), self.root / 'absent'))
        self.assertFalse((self.root / 'absent').exists())
        files = {guest_resources.MANIFEST: canonical({'schemaVersion': guest_resources.PROFILE, 'resources': []})}
        output = self.root / 'empty'
        self.assertEqual(resources.materialize(files, inventory(files), (), output), output)
        self.assertEqual(resources.source_inputs(output), {})

    def test_stage_binds_literal_generated_sources_resources_and_exact_original_classlib(self):
        self.put('outside/badge.txt', b'\x00\xff\n')
        self.put('data/\u96ea.bin', b'empty-next')
        receipt = resources.stage(self.sdk, self.data, self.project)
        self.assertEqual(receipt['resourceInputs'], json.loads(inventory(resources.source_inputs(self.data))))
        self.assertEqual(receipt['classlibPreimage'], resources.CLASSLIB)
        self.assertEqual(receipt['method'], resources.METHOD)
        self.assertEqual(receipt['identity'], digest(canonical({k: v for k, v in receipt.items() if k != 'identity'})))
        sources = resources.generated_sources(resources.source_inputs(self.data))
        for name, data in sources.items():
            self.assertEqual((self.project / 'src/main/java/dev/latent/guest/resources' / name).read_bytes(), data)
        self.assertEqual(receipt['generatedSources'], json.loads(inventory(sources)))
        resources.recheck(self.data, receipt)
        self.assertNotIn(b'java.lang.ClassLoader', sources['ImmutableResources.java'])

    def test_resource_recheck_denies_changed_added_removed_or_aliased_bytes(self):
        self.put('outside/badge', b'original')
        receipt = resources.stage(self.sdk, self.data, self.project)
        for action in ('change', 'add', 'remove'):
            with self.subTest(action=action):
                self.put('outside/badge', b'changed' if action == 'change' else b'original')
                if action == 'add': self.put('outside/extra', b'extra')
                if action == 'remove': (self.data / 'outside/badge').unlink()
                with self.assertRaisesRegex(ValueError, 'inputs changed'):
                    resources.recheck(self.data, receipt)
                if (self.data / 'outside/extra').exists(): (self.data / 'outside/extra').unlink()

    def test_literal_java_chunks_and_method_sizes_are_bounded_without_discarding_bytes(self):
        payload = bytes(range(256)) * 512
        generated = resources.generated_sources({'data/quote-\u96ea.txt': payload})
        parts = [data for name, data in generated.items() if 'Part' in name]
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(part) < 34000 for part in parts))
        self.assertIn(b'java.util.Objects.requireNonNull(name)', generated['ImmutableResources.java'])
        self.assertIn(b'default: return null;', generated['ImmutableResources.java'])
        self.assertIn(b'\\u96ea', generated['ImmutableResources.java'])
        self.assertIn(b'new java.io.ByteArrayInputStream', generated['Data0000.java'])
        self.assertEqual(generated, resources.generated_sources({'data/quote-\u96ea.txt': payload}))

    def test_immutable_sdk_or_generated_source_collision_fails_before_compiler(self):
        self.put('outside/badge', b'bytes')
        destination = self.project / 'src/main/java/dev/latent/guest/resources/ImmutableResources.java'
        destination.parent.mkdir(parents=True); destination.write_bytes(b'preexisting owned source')
        with self.assertRaisesRegex(ValueError, 'source collision'):
            resources.stage(self.sdk, self.data, self.project)
        self.assertEqual(destination.read_bytes(), b'preexisting owned source')
        changed = copy.deepcopy(json.loads((self.sdk / 'feasibility/dependencies.lock.json').read_bytes()))
        for row in changed['artifacts']:
            if row['path'] == resources.CLASSLIB['path']: row['sha256'] = '0' * 64
        with patch.object(resources, 'read_file', return_value=canonical(changed)):
            with self.assertRaisesRegex(ValueError, 'preimage changed'):
                resources.stage(self.sdk, self.data, self.root / 'unused-project')

    def test_sdk_service_merge_preserves_profiles_and_denies_duplicates_and_unowned_services(self):
        service = self.project / 'services/org.teavm.vm.spi.TeaVMPlugin'
        name = 'META-INF/services/org.teavm.vm.spi.TeaVMPlugin'
        stage_sdk_service(service, name, b'dev.latent.guest.runtime.compiler.RuntimePlugin\n')
        stage_sdk_service(service, name, b'dev.latent.guest.resources.compiler.ImmutableResourcePlugin\n')
        original = service.read_bytes()
        self.assertEqual(original.splitlines(), [b'dev.latent.guest.runtime.compiler.RuntimePlugin',
                                               b'dev.latent.guest.resources.compiler.ImmutableResourcePlugin'])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            stage_sdk_service(service, name, b'dev.latent.guest.runtime.compiler.RuntimePlugin\n')
        with self.assertRaisesRegex(ValueError, 'invalid Java SDK'):
            stage_sdk_service(service, 'META-INF/services/outside.application.Plugin', b'outside.application.Plugin\n')
        self.assertEqual(service.read_bytes(), original)

    def test_resource_port_is_part_of_each_new_project_sdk_source_identity(self):
        sources = sdk_snapshot(self.sdk)
        self.assertIn('resources/compiler/dev/latent/guest/resources/compiler/ImmutableResourcePlugin.java', sources)
        self.assertEqual(sources['resources/services/META-INF/services/org.teavm.vm.spi.TeaVMPlugin'],
                         b'dev.latent.guest.resources.compiler.ImmutableResourcePlugin\n')

    def test_service_merge_count_and_byte_limits_preserve_the_existing_profile(self):
        name = 'META-INF/services/org.teavm.vm.spi.TeaVMPlugin'
        for previous, selected in (
                (b''.join(('dev.latent.Profile' + str(index) + '\n').encode() for index in range(128)),
                 b'dev.latent.NewProfile\n'),
                (('dev.latent.' + 'A' * 10000 + '\n').encode(),
                 ('dev.latent.' + 'B' * 10000 + '\n').encode())):
            service = self.project / ('service-' + str(len(previous)))
            service.write_bytes(previous)
            with self.assertRaisesRegex(ValueError, 'merge limit'):
                stage_sdk_service(service, name, selected)
            self.assertEqual(service.read_bytes(), previous)

    def test_server_and_resource_profiles_preserve_both_trusted_services_before_compilation(self):
        from tools.java_guest import compiler as java_compiler

        self.put('outside/badge.txt', b'\x00selected\xff')
        sources = self.root / 'source'; sources.mkdir()
        (sources / 'Main.java').write_text('final class Main {}\n', encoding='utf-8')
        wit = self.root / 'wit'; wit.mkdir()
        (wit / 'world.wit').write_text('package outside:fixture; world service {}\n', encoding='utf-8')
        owner = java_compiler.Compiler.__new__(java_compiler.Compiler)
        owner.sdk, owner.platform, owner.offline = self.sdk, ROOT / 'wit/platform', True

        def generated(_run, _wit, _world, destination):
            destination.mkdir()
            (destination / 'Bindings.java').write_bytes(b'// controlled binding boundary\n')
            return {'source': 'controlled-binding'}

        class CompileBoundary(Exception):
            pass

        invoked = []
        def stop(stage, tool, *arguments, cwd=None):
            invoked.append((stage, tool, arguments, cwd))
            raise CompileBoundary()

        owner.run = stop
        destination = self.root / 'compiled'
        with patch.object(java_compiler, 'generate', side_effect=generated):
            with self.assertRaises(CompileBoundary):
                owner.compile(sources, wit, 'outside:fixture/service', destination,
                              application_resources=self.data, server_profile=True)
        self.assertEqual(len(invoked), 1)
        self.assertEqual(invoked[0][:2], ('java-to-c', 'gradle'))
        self.assertIn('--offline', invoked[0][2])
        project = destination / 'project'
        self.assertEqual(invoked[0][3], project)
        for name in ('META-INF/services/org.teavm.vm.spi.TeaVMPlugin',
                     'META-INF/services/org.teavm.extension.spi.substitution.SubstitutionPolicy'):
            expected = (self.sdk / 'server/services' / name).read_bytes().splitlines()
            if name.endswith('TeaVMPlugin'):
                expected = (self.sdk / 'resources/services' / name).read_bytes().splitlines() + expected
            self.assertEqual((project / 'src/main/resources' / name).read_bytes().splitlines(), expected)
        self.assertTrue((project / 'src/main/java/dev/latent/guest/server/http/HttpServer.java').is_file())
        self.assertTrue((project / 'src/main/java/dev/latent/guest/resources/ImmutableResources.java').is_file())
        receipt = json.loads((destination / 'resource-profile.json').read_bytes())
        self.assertEqual(receipt['resourceInputs'], json.loads(inventory(resources.source_inputs(self.data))))


if __name__ == '__main__':
    unittest.main()
