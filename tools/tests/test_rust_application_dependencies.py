"""Native Cargo provenance, path relocation and executable-input controls."""
from pathlib import Path
import tempfile
import tomllib
import unittest

from tools.application_dependencies import LOCK, MANIFEST, capture, prepare
from tools.application_dependency_store import DependencyError
from tools.build_snapshot import canonical, digest
from tools.rust_application_dependencies import analyze, configure, package_identity, selected_manifest
from tools.rust_capsule_project import create, snapshot
from tools.rust_capsule_build import validate_project


class CargoDependencies(unittest.TestCase):
    def test_selected_native_paths_relocate_without_changing_source_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = b'[dependencies]\nprivate = { path = "../developer", features = ["pure"] }\n[lib]\npath = "src/lib.rs"\n'
            source = root / 'project/Cargo.toml'
            adapted = selected_manifest(raw, source, Path('Cargo.toml'),
                {(root / 'developer').resolve(): Path('dependencies/cargo-paths/unknown')})
            self.assertEqual(tomllib.loads(adapted.decode())['dependencies']['private']['path'], 'dependencies/cargo-paths/unknown')
            self.assertEqual(tomllib.loads(adapted.decode())['lib']['path'], 'src/lib.rs')
            self.assertIn(b'../developer', raw)

    def test_external_path_not_selected_by_native_resolver_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(DependencyError, 'not-in-selected-graph'):
                selected_manifest(b'[dependencies]\nprivate = {path="../outside"}\n', Path(temporary) / 'project/Cargo.toml', Path('Cargo.toml'), {})

    def test_package_coordinates_are_provenance_without_catalogue_membership(self):
        self.assertNotEqual(package_identity({'name': 'outside', 'version': '1.0.0', 'id': 'developer-a'}),
                            package_identity({'name': 'outside', 'version': '1.0.0', 'id': 'developer-b'}))

    def test_normal_path_declarations_require_reviewed_capture_extension(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = create(Path(temporary) / 'project', 'greeting')
            with (root / 'Cargo.toml').open('ab') as output:
                output.write(b'\n[dependencies]\nprivate = {path="../outside"}\n')
            files = snapshot(root)
            with self.assertRaisesRegex(ValueError, 'exact versions'):
                validate_project(files)
            manifest = {'formatVersion': 1, 'language': 'rust', 'selection': {'target': 'wasm32-unknown-unknown'},
                        'nativeLocks': ['Cargo.lock'], 'artifacts': [], 'transformations': []}
            files[MANIFEST] = canonical(manifest)
            validate_project(files)  # Execution still requires verified native closure.

    def test_native_graph_must_include_every_selected_dependency(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(DependencyError, 'not-closed'):
                analyze({'version': 1, 'packages': [{'id': 'outside'}], 'resolve': {'nodes': []}}, root, root, {})

    def test_build_macros_need_explicit_separate_isolated_stage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, library, work, output = (root / name for name in ('project', 'library', 'work', 'output'))
            for path in (project, library, work, output): path.mkdir()
            (library / 'build.rs').write_bytes(b'fn main() {}')
            manifest = {'formatVersion': 1, 'language': 'rust', 'selection': {}, 'nativeLocks': [],
                        'artifacts': [{'id': 'developer/build-script/1', 'role': 'build-tool', 'format': 'directory',
                            'mount': 'dependencies/macro', 'source': {'path': str(library)}, 'dependencies': [],
                            'metadata': {'ecosystem': 'cargo', 'executableKinds': [['custom-build']]}}], 'transformations': []}
            (project / MANIFEST).write_bytes(canonical(manifest))
            (project / LOCK).write_bytes(canonical(capture(project)))
            with self.assertRaisesRegex(DependencyError, 'isolated-stage'):
                prepare(project, work, output, 'rust')

    def test_native_vendor_configuration_is_owned_offline_and_attributable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, work, output = (root / name for name in ('project', 'work', 'output'))
            for path in (project, work, output): path.mkdir()
            source = project / 'Cargo.toml'
            source.write_bytes(b'[package]\nname="outside"\nversion="1.0.0"\n')
            graph = {'sourceReplacement': {'source': {'crates-io': {'replace-with': 'captured'},
                                                       'captured': {'directory': 'dependencies/cargo-vendor'}}}}
            (project / 'cargo-resolved.lock.json').write_bytes(canonical(graph))
            manifest = {'formatVersion': 1, 'language': 'rust', 'selection': {}, 'nativeLocks': ['cargo-resolved.lock.json'],
                'artifacts': [{'id': 'root/1', 'role': 'generated', 'format': 'file', 'mount': 'application-vendor/root/Cargo.toml',
                              'source': {'path': str(source)}, 'dependencies': [], 'metadata': {'rootManifest': True}}], 'transformations': []}
            (project / MANIFEST).write_bytes(canonical(manifest))
            (project / LOCK).write_bytes(canonical(capture(project)))
            closure = prepare(project, work, output, 'rust')
            (work / 'Cargo.toml').write_bytes(source.read_bytes())
            adapted, receipt = configure(closure, work, root / 'private-home')
            self.assertEqual(adapted, source.read_bytes())
            self.assertEqual(receipt['inputIdentity'], closure.identity)
            config = tomllib.loads((root / 'private-home/config.toml').read_text())
            self.assertTrue(config['net']['offline'])
            self.assertEqual(config['source']['captured']['directory'], str(work / 'dependencies/cargo-vendor'))

    def test_native_root_manifest_cannot_silently_ignore_edits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work = root / 'work'
            work.mkdir()
            (work / 'Cargo.toml').write_bytes(b'[package]\nname="changed"\n')
            class Closure:
                project = root
                lock = {'artifacts': [{'metadata': {'rootManifest': True}, 'original': {'digest': digest(b'old')}}]}
            (root / 'cargo-resolved.lock.json').write_bytes(canonical({'sourceReplacement': {}}))
            with self.assertRaisesRegex(DependencyError, 'root-manifest-drift'):
                configure(Closure(), work, root / 'home')


class DirectFixtureLibraries(unittest.TestCase):
    def setUp(self):
        from tools.rust_dependency_fixture import direct_libraries
        self.verify = direct_libraries
        self.required = {('unlisted-pure-crate', '1.2.3'): 'ordinary_pure_api',
                         ('unlisted-developer-crate', '4.5.6'): 'ordinary_developer_api'}
        identities = ['native-pure', 'native-developer']
        self.artifacts = [{'id': name + '/' + version, 'role': 'application',
                           'metadata': {'package': name, 'version': version, 'nativeIdDigest': digest(identity.encode())}}
                          for (name, version), identity in zip(self.required, identities)]
        edges = [{'pkg': identity} for identity in identities]
        self.graph = {'root': 'native-application',
                      'nodes': [{'id': 'native-application', 'artifact': None, 'dependencies': edges.copy()}]
                               + [{'id': identity, 'artifact': artifact['id'], 'dependencies': []}
                                  for identity, artifact in zip(identities, self.artifacts)],
                      'selectedResolve': {'root': 'native-application',
                                          'nodes': [{'id': 'native-application', 'deps': edges.copy()}]}}

    def test_two_ordinary_application_libraries_bind_exact_native_artifacts(self):
        result = self.verify(self.graph, self.artifacts, self.required)
        self.assertEqual([row['artifact'] for row in result], [row['id'] for row in self.artifacts])
        self.assertEqual([row['ordinaryApi'] for row in result], list(self.required.values()))
        self.assertTrue(all(row['selection'] == 'application-root-direct' for row in result))

    def test_transitive_presence_cannot_replace_independent_application_selection(self):
        self.graph['nodes'][0]['dependencies'].pop(0)
        self.graph['nodes'][2]['dependencies'].append({'pkg': 'native-pure'})
        self.graph['selectedResolve']['nodes'][0]['deps'].pop(0)
        with self.assertRaisesRegex(ValueError, 'not independently selected'):
            self.verify(self.graph, self.artifacts, self.required)

    def test_dependency_unselected_for_actual_target_cannot_claim_application_selection(self):
        self.graph['selectedResolve']['nodes'][0]['deps'].pop()
        with self.assertRaisesRegex(ValueError, 'not independently selected'):
            self.verify(self.graph, self.artifacts, self.required)

    def test_ambiguous_root_or_forged_artifact_cannot_claim_native_selection(self):
        self.graph['selectedResolve']['root'] = 'changed-root'
        with self.assertRaisesRegex(ValueError, 'ambiguous or missing'):
            self.verify(self.graph, self.artifacts, self.required)
        self.graph['selectedResolve']['root'] = self.graph['root']
        self.graph['nodes'][1]['artifact'] = 'different-artifact'
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.verify(self.graph, self.artifacts, self.required)


class StagedRustLinker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import sys
        if sys.platform != "linux":
            raise unittest.SkipTest("Maintained Rust compiler discovery requires Linux")

    def fixture(self, root, *, version=None, sdk_shadow=False):
        from tools import dev_guest_recipe as adapter
        version = adapter.ZIG_VERSION if version is None else version
        payload, attempt, ambient = root / "payload", root / "attempt", root / "ambient"
        sdk = payload / "sdk"
        for path in (sdk / "bin", sdk / "registry/index", attempt / "app", attempt / "build-cache/zig", ambient):
            path.mkdir(parents=True)
        (sdk / "registry/index/record").write_bytes(b"immutable captured Cargo index")
        zig = attempt / "build-cache/zig/zig"
        zig.write_text("#!/bin/sh\nprintf '%s\\n' '" + version + "'\n", encoding="utf-8")
        zig.chmod(0o700)
        competitor = sdk / "bin/zig" if sdk_shadow else ambient / "zig"
        competitor.write_text("#!/bin/sh\nprintf '%s\\n' 'ambient-compiler'\n", encoding="utf-8")
        competitor.chmod(0o700)
        return payload, attempt / "app", attempt / "output", zig, ambient

    def test_captured_compiler_discovers_staged_zig_without_inherited_tool_paths(self):
        import os
        import shutil
        from unittest.mock import ANY, patch
        from tools import dev_guest_recipe as adapter, rust_capsule_build
        for sdk_shadow in (False, True):
            with self.subTest(sdk_shadow=sdk_shadow), tempfile.TemporaryDirectory(prefix="rust linker spaces-") as temporary:
                payload, project, output, zig, ambient = self.fixture(Path(temporary), sdk_shadow=sdk_shadow)
                sdk = payload / "sdk"
                approval = "sha256:" + "a" * 64

                def selected_build(*args, **kwargs):
                    # Exercise captured isolation's real executable discovery;
                    # this fixture contains no native compiler products.
                    selected = shutil.which("zig", path=os.environ["PATH"])
                    self.assertIsNotNone(selected, "Already staged Zig must be discoverable by the captured compiler")
                    self.assertEqual(Path(selected).resolve(), zig.resolve())
                    self.assertIsNotNone(shutil.which("sh", path=os.environ["PATH"]))
                    self.assertNotIn(str(ambient), os.environ["PATH"].split(os.pathsep))
                    self.assertEqual(args, (project, output, sdk / "bin/capsule-contracts", None,
                                           "https://github.com/KirilsTurkins/latent-service-fabric"))
                    self.assertEqual(kwargs, {"offline": True, "host_linker": project.parent / "build-cache/host-linker",
                                              "rust_bin": sdk / "rust/bin", "executable_approval": approval})

                with patch.dict(os.environ, {"PATH": str(ambient), "CARGO_HOME": str(ambient / "cargo")}), \
                        patch.object(adapter.platform, "machine", return_value="x86_64"), \
                        patch.object(adapter, "unpack_zig", return_value=zig) as unpacked, \
                        patch.object(adapter, "run_bounded", wraps=adapter.run_bounded) as version_probe, \
                        patch.object(rust_capsule_build, "build", side_effect=selected_build) as built:
                    adapter.compile_rust(payload, project, output, lambda: None, executable_approval=approval)
                    built.assert_called_once()
                    unpacked.assert_called_once_with(sdk / "zig.tar.xz", project.parent / "build-cache/zig", ANY)
                    self.assertEqual(version_probe.call_args.args[0], [str(zig), "version"])
                    self.assertEqual(version_probe.call_args.kwargs["timeout_seconds"], 10)
                    self.assertEqual(version_probe.call_args.kwargs["max_output_bytes"], 1024)
                self.assertEqual((sdk / "registry/index/record").read_bytes(), b"immutable captured Cargo index")
                self.assertEqual((project.parent / "build-cache/cargo/registry/index/record").read_bytes(),
                                 b"immutable captured Cargo index")

    def test_wrong_staged_zig_version_fails_before_linker_or_compiler_selection(self):
        import os
        from unittest.mock import patch
        from tools import dev_guest_recipe as adapter, rust_capsule_build
        from tools.dev_workflow.common import DevError
        with tempfile.TemporaryDirectory() as temporary:
            payload, project, output, zig, ambient = self.fixture(Path(temporary), version="0.15.0")
            with patch.dict(os.environ, {"PATH": str(ambient)}), \
                    patch.object(adapter.platform, "machine", return_value="x86_64"), \
                    patch.object(adapter, "unpack_zig", return_value=zig), \
                    patch.object(adapter, "linker") as linker, \
                    patch.object(rust_capsule_build, "build") as built:
                with self.assertRaisesRegex(DevError, "guest-linker-version"):
                    adapter.compile_rust(payload, project, output, lambda: None)
                linker.assert_not_called()
                built.assert_not_called()
                self.assertNotIn(str(zig.parent), os.environ["PATH"].split(os.pathsep))
            self.assertFalse(output.exists())
            self.assertFalse((project.parent / "build-cache/host-linker").exists())


if __name__ == '__main__':
    unittest.main()
