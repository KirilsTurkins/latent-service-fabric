"""Authoring boundaries; compiler/provider execution stays in the real gate."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from tools import rust_capsule_build as build
from tools import rust_capsule_project as project
from tools import rust_standard_logging_inputs as standard


class RustProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix="rust-authoring-tests-")
        cls.addClassCleanup(cls.workspace.cleanup)
        cls.source = project.create(Path(cls.workspace.name) / "project", "greeting")
        cls.inputs = project.snapshot(cls.source)

    def files(self):
        return dict(self.inputs)

    def changed(self, filename, change):
        files = self.files()
        value = json.loads(files[filename])
        change(value)
        files[filename] = json.dumps(value).encode()
        return files

    def test_independent_project_preserves_canonical_source_and_exact_lock(self):
        value, pins = build.validate_project(self.files())
        cargo = tomllib.loads(self.inputs["Cargo.toml"].decode())
        self.assertEqual(cargo["package"]["name"], "my-greeting")
        self.assertEqual(cargo["lib"], {"crate-type": ["cdylib"]})
        self.assertEqual(value["world"], "examples:greeting/service@1.0.0")
        source = project.ROOT / pins["template"]["source"] / "component.rs"
        self.assertEqual(project.digest(source.read_bytes()), pins["template"]["componentDigest"])
        self.assertEqual(source.read_bytes().replace(b'path: "examples/tutorial_greeting"', b'path: "wit"'), self.inputs["src/lib.rs"])
        self.assertNotIn(b"latent-node", self.inputs["Cargo.lock"])

    def test_all_tutorials_and_capability_examples_create_valid_standalone_inputs(self):
        for template in project.TEMPLATES:
            with self.subTest(template=template), tempfile.TemporaryDirectory() as temp:
                root = project.create(Path(temp) / "project", template)
                value, _pins = build.validate_project(project.snapshot(root))
                self.assertEqual(value["world"], f"examples:{template}/service@1.0.0")
                self.assertEqual(value["limits"]["outboundRequests"], int(template == "http-status"))

    def test_fresh_projects_never_overwrite_existing_files(self):
        before = project.snapshot(self.source)
        with self.assertRaisesRegex(ValueError, "fresh"):
            project.create(self.source, "shipping")
        self.assertEqual(project.snapshot(self.source), before)

    def test_nonportable_and_colliding_package_names_are_rejected_before_creation(self):
        for name in ("../escape", "Cap", "a--b", "a_underscore", "x" * 65, "wit-bindgen"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                out = Path(temp) / "project"
                with self.assertRaises(ValueError):
                    project.create(out, "greeting", name)
                self.assertFalse(out.exists())

    def test_reviewed_dependency_lock_rejects_changed_authoritative_checksums(self):
        original = project.ROOT
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "tools").mkdir()
            (root / "tools/rust_capsule.lock").write_bytes((original / "tools/rust_capsule.lock").read_bytes())
            (root / "Cargo.lock").write_text('version = 4\npackage = []\n')
            with patch.object(project, "ROOT", root), self.assertRaisesRegex(ValueError, "lock drift"):
                project.locked_dependencies("my-project")

    def test_edited_sdk_does_not_satisfy_the_original_source_lock(self):
        files = self.files()
        files["vendor/lsf/sdk/rust-guest/src/blob.rs"] += b"\n// edited\n"
        with self.assertRaisesRegex(ValueError, "vendored SDK changed"):
            build.validate_project(files)

    def test_sdk_inheritance_cannot_introduce_uncaptured_dependency_overrides(self):
        files = self.files()
        files["Cargo.toml"] = files["Cargo.toml"].replace(b"[workspace.dependencies]", b'[workspace.dependencies]\ninjected = { path = "/escape" }', 1)
        self.assertNotEqual(files["Cargo.toml"], self.inputs["Cargo.toml"])
        with self.assertRaisesRegex(ValueError, "inheritance"):
            build.validate_project(files)

    def test_cargo_configuration_and_toolchain_overrides_are_rejected(self):
        for key, value in ((".cargo/config.toml", b'[build]\nrustc-wrapper = "/escape"'),
                           ("rust-toolchain.toml", b'[toolchain]\nchannel = "nightly"')):
            with self.subTest(key=key):
                files = self.files()
                files[key] = value
                with self.assertRaises(ValueError):
                    build.validate_project(files)

    def test_cargo_and_manifest_identity_must_agree(self):
        files = self.changed("capsule-project.json", lambda value: value.update(name="other"))
        with self.assertRaisesRegex(ValueError, "identities disagree"):
            build.validate_project(files)

    def test_manifest_fields_budgets_and_versions_are_closed(self):
        changes = [lambda value: value.update(extra=True), lambda value: value.update(formatVersion=True),
                   lambda value: value.update(name=[]), lambda value: value.update(limits=[]),
                   lambda value: value["limits"].update(cpuFuel=True), lambda value: value["limits"].update(cpuFuel=0),
                   lambda value: value["limits"].update(memoryBytes=2**64), lambda value: value["limits"].update(logBytes=-1)]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                build.validate_project(self.changed("capsule-project.json", change))

    def test_sdk_lock_shape_and_version_fail_closed(self):
        for value in ([], {"formatVersion": 1}, {"formatVersion": True}, None):
            files = self.files()
            files["sdk-lock.json"] = json.dumps(value).encode()
            with self.subTest(value=value), self.assertRaises(ValueError):
                build.validate_project(files)

    def test_duplicate_nonfinite_and_excessively_nested_json_are_rejected(self):
        for data in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'[' * 2000 + b']' * 2000, b'"\xff"'):
            with self.subTest(data=data[:20]), self.assertRaises(ValueError):
                project.decode_json(data)

    def test_captured_application_code_can_change_without_runtime_edits(self):
        files = self.files()
        files["src/lib.rs"] = files["src/lib.rs"].replace(b"Hello,", b"Welcome,")
        build.validate_project(files)
        self.assertNotEqual(project.inventory(files), project.inventory(self.files()))

    def test_additional_dependencies_require_exact_versions_and_no_path_escape(self):
        for spec in ('"1.0"', '{path="/outside"}', '{version="=1.0.0",git="https://invalid/repo"}', '[]'):
            files = self.files()
            files["Cargo.toml"] += f'\n[dependencies]\nextra = {spec}\n'.encode()
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                build.validate_project(files)
        files["Cargo.toml"] = self.inputs["Cargo.toml"] + b'\n[dependencies]\nextra = "=1.0.0"\n'
        build.validate_project(files)

    def test_build_script_must_be_captured_not_an_absolute_escape(self):
        files = self.files()
        files["Cargo.toml"] = files["Cargo.toml"].replace(b'publish = false', b'publish = false\nbuild = "/outside/build.rs"')
        with self.assertRaisesRegex(ValueError, "build script"):
            build.validate_project(files)

    def test_snapshot_excludes_only_root_build_and_git_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for directory in ("target", ".git", "source/target"):
                (root / directory).mkdir(parents=True)
                (root / directory / "file").write_bytes(b"data")
            self.assertEqual(project.snapshot(root), {"source/target/file": b"data"})

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_snapshot_rejects_linked_files_directories_and_ancestors(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "source").mkdir()
            (root / "source/data").write_bytes(b"data")
            (root / "alias").symlink_to(root / "source", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                project.snapshot(root / "alias")
            (root / "alias").unlink()
            (root / "source/link").symlink_to(root / "source/data")
            with self.assertRaisesRegex(ValueError, "regular file"):
                project.snapshot(root / "source")

    def test_snapshot_enforces_file_byte_count_and_total_budgets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "file").write_bytes(b"12345")
            with self.assertRaises(ValueError):
                project.read_file(root / "file", 4)
            with patch.object(project, "MAX_SOURCE", 4), self.assertRaises(ValueError):
                project.snapshot(root)
            with patch.object(project, "MAX_FILES", 0), self.assertRaises(ValueError):
                project.snapshot(root)

    def test_build_rejects_source_output_overlap_before_tool_execution(self):
        for output in (self.source, self.source.parent, self.source / "artifacts"):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, "overlap|inside target"):
                build.build(self.source, output, Path("missing"), Path("missing"), "https://example.com/repo")

    def test_build_failure_retains_stage_but_cannot_publish_a_success_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "failed"
            with patch.object(build, "resolve_tools", side_effect=ValueError("pinned compiler unavailable")):
                with self.assertRaisesRegex(ValueError, "pinned compiler"):
                    build.build(self.source, output, Path("missing"), Path("missing"), "https://example.com/repo")
            record = project.read_json(output / "BUILD-FAILED.json")
            self.assertEqual(record["stage"], "prepare")
            self.assertEqual(record["commands"], [])
            self.assertFalse((output / "BUILD-COMPLETE.json").exists())
            self.assertFalse((output / "build-observation.json").exists())

    def test_opt_in_diagnostics_keep_nonzero_status_without_false_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            commands = build.Commands(root, root, dict(os.environ))
            with self.assertRaisesRegex(ValueError, "compile failed"):
                commands.run("compile", sys.executable, "-c", "import sys; print('typed compiler error',file=sys.stderr); sys.exit(7)")
            self.assertEqual(commands.records[0]["exitCode"], 7)
            self.assertEqual((root / "logs/00-compile.stderr.txt").read_text(), "typed compiler error\n")

    def test_overall_command_deadline_precedes_child_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            commands = build.Commands(root, root, {})
            commands.deadline = 0
            with self.assertRaisesRegex(ValueError, "deadline"):
                commands.run("compile", "not-a-command")
            self.assertEqual(commands.records, [])


if __name__ == "__main__":
    unittest.main()


class RustDeclaredEnvironment(unittest.TestCase):
    """Digest/namespace/approval controls; no compiler or namespace is executed."""
    def fixture(self):
        from tools.build_observation import file_identity
        from tools.captured_compiler_isolation import Isolation, distribution
        from tools.build_snapshot import digest
        temporary = tempfile.TemporaryDirectory(prefix='rust-environment-control-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        workspace, compiler, zig = root / 'attempt', root / 'rust', root / 'zig'
        for path in (workspace, compiler, zig): path.mkdir()
        tools = {}
        for name in ('cargo', 'rustc', 'wasm-tools', 'wit-bindgen', 'shell', 'linker', 'zig'):
            path = (zig if name == 'zig' else compiler) / name
            path.write_bytes(('captured source-control tool: ' + name).encode())
            tools[name] = path
        scope = object.__new__(Isolation)
        scope.workspace, scope.tools, scope.sandbox = workspace, tools, tools['shell']
        scope.distributions = {'rust-compiler-and-sysroot': compiler, 'zig-host-linker-and-sysroot': zig}
        scope.read_only_inputs, scope.child_path, scope.loader_directories, scope.shared = [], None, (), {}
        scope.before = {name: distribution(path) for name, path in scope.distributions.items()}
        scope.tool_before = {name: file_identity(path, name) for name, path in tools.items()}
        scope.sandbox_before = file_identity(scope.sandbox, 'build-sandbox')
        scope.receipt = {'formatVersion': 1, 'profile': 'linux-captured-compiler-namespaces-v1',
            'distributions': scope.before, 'tools': scope.tool_before, 'sandbox': scope.sandbox_before,
            'loaderObserver': file_identity(tools['shell'], 'loader-dependency-observer'), 'hostRuntimeLibraries': {},
            'network': 'denied', 'ambientHome': 'absent', 'credentials': 'not-inherited',
            'boundary': 'trusted-single-user-compiler-host-not-hardened-multitenant-vm'}
        environment = {'LC_ALL': 'C', 'TZ': 'UTC', 'CARGO_BUILD_JOBS': '2', 'CARGO_INCREMENTAL': '0',
            'CARGO_NET_OFFLINE': 'true', 'RUSTUP_AUTO_INSTALL': '0', 'RUSTUP_TOOLCHAIN': '1.97.1',
            'RUSTC': str(tools['rustc']), 'CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER': str(tools['linker']),
            'LSF_CAPTURED_ZIG': str(tools['zig']), 'CARGO_HOME': str(workspace / 'cargo-home'),
            'CARGO_TARGET_DIR': str(workspace / 'target'), 'ZIG_GLOBAL_CACHE_DIR': str(workspace / 'zig-global'),
            'ZIG_LOCAL_CACHE_DIR': str(workspace / 'zig-local')}
        return workspace, scope, environment

    def verified(self):
        from types import SimpleNamespace
        return SimpleNamespace(identity=project.digest(b'captured-inputs'), lock={'transformations': [], 'artifacts': [
            {'id': 'outside/build-script', 'role': 'build-tool'}], 'selection': {'runtimeProfile': 'closed'}})

    def test_actual_approval_is_stable_across_distinct_owned_build_roots(self):
        from tools.application_dependency_approval import approve, request
        first, a, env_a = self.fixture()
        second, b, env_b = self.fixture()
        build.RustEnvironment(env_a, a); build.RustEnvironment(env_b, b)
        recipe, verified = project.digest(b'fixed-recipe'), self.verified()
        req_a, req_b = request(verified, a, recipe), request(verified, b, recipe)
        self.assertNotEqual(first, second)
        self.assertEqual(req_a, req_b)
        identity = project.digest(project.canonical(req_a))
        consent = approve(verified, b, recipe, identity)
        consent.validate(verified, second)
        raw = project.canonical(req_b)
        self.assertNotIn(str(first).encode(), raw)
        self.assertNotIn(str(second).encode(), raw)

    def test_changed_and_new_forwarded_values_refuse_before_any_compile_dispatch(self):
        from unittest.mock import Mock
        from tools.application_dependency_store import DependencyError
        workspace, scope, environment = self.fixture()
        guard = build.RustEnvironment(environment, scope)
        original = dict(environment)
        commands = Mock(environment=environment)
        for key, changed in [('CARGO_BUILD_JOBS', '3'), ('LANG', 'C.UTF-8'),
                             ('ZIG_GLOBAL_CACHE_DIR', str(workspace / 'other-cache'))]:
            with self.subTest(key=key):
                environment.clear(); environment.update(original); environment[key] = changed
                with self.assertRaisesRegex(DependencyError, '^cargo-execution-environment-mutated$'):
                    guard.compile(commands, scope.tools['cargo'], ['build', '--locked'], workspace)
                commands.run.assert_not_called()
        environment.clear(); environment.update(original)
        commands.run.return_value = b'controlled result'
        self.assertEqual(guard.compile(commands, scope.tools['cargo'], ['build', '--locked'], workspace), b'controlled result')
        commands.run.assert_called_once()

    def test_new_valid_selection_changes_the_actual_request_and_refuses_old_consent(self):
        from tools.application_dependency_approval import approve, request
        from tools.application_dependency_store import DependencyError
        _first, a, env_a = self.fixture(); second, b, env_b = self.fixture()
        env_b['CARGO_BUILD_JOBS'] = '3'; env_b['ZIG_GLOBAL_CACHE_DIR'] = str(second / 'different-cache')
        build.RustEnvironment(env_a, a); build.RustEnvironment(env_b, b)
        recipe, verified = project.digest(b'fixed-recipe'), self.verified()
        old = project.digest(project.canonical(request(verified, a, recipe)))
        self.assertNotEqual(request(verified, a, recipe), request(verified, b, recipe))
        with self.assertRaisesRegex(DependencyError, 'approval-mismatch'):
            approve(verified, b, recipe, old)

    def test_scalar_bounds_and_types_fail_with_a_closed_nonsecret_diagnostic(self):
        from tools.application_dependency_store import DependencyError
        _workspace, scope, environment = self.fixture()
        for value in (None, True, 4, 'private-' + 'sentinel\n', 'x' * 4097, '\ud800'):
            with self.subTest(kind=type(value).__name__), self.assertRaises(DependencyError) as caught:
                build.environment_material({**environment, 'LC_ALL': value}, scope)
            self.assertEqual(str(caught.exception), 'cargo-execution-environment-invalid')

    def test_paths_require_owned_directories_or_the_exact_captured_tool(self):
        from tools.application_dependency_store import DependencyError
        workspace, scope, environment = self.fixture()
        for key, value in [('CARGO_HOME', str(workspace.parent / 'foreign')), ('CARGO_TARGET_DIR', 'relative'),
                           ('ZIG_LOCAL_CACHE_DIR', str(scope.tools['cargo'])),
                           ('RUSTC', str(scope.tools['cargo'])), ('RUSTDOC', str(scope.tools['rustc']))]:
            with self.subTest(key=key), self.assertRaisesRegex(DependencyError, '^cargo-execution-environment-invalid$'):
                build.environment_material({**environment, key: value}, scope)

    def test_actual_namespace_forwarding_is_covered_without_disclosing_private_values(self):
        workspace, scope, environment = self.fixture()
        marker = 'private-' + 'scalar-marker'
        environment.update(LANG=marker, X_UNSELECTED_CREDENTIAL=marker + '-unselected', HOME=marker + '-home')
        guard = build.RustEnvironment(environment, scope)
        argv = scope.wrap(scope.tools['cargo'], ['build'], workspace, environment)
        forwarded = {argv[index + 1]: argv[index + 2] for index, value in enumerate(argv) if value == '--setenv'}
        material = scope.receipt['declaredEnvironment']
        observed = {key for group in ('scalars', 'paths') for key, value in material[group].items() if value is not None}
        self.assertEqual(set(forwarded), observed | {'HOME', 'PATH'})
        self.assertEqual(forwarded['HOME'], '/home')
        self.assertEqual(forwarded['PATH'], '/nonexistent')
        self.assertNotIn(marker + '-unselected', argv)
        self.assertNotIn(marker + '-home', argv)
        raw = project.canonical(scope.receipt)
        self.assertNotIn(marker.encode(), raw)
        self.assertNotIn(str(workspace).encode(), raw)
        guard.check_unchanged(environment)

    def test_receipt_rewriting_or_rebinding_cannot_promote_a_changed_environment(self):
        from tools.application_dependency_store import DependencyError
        _workspace, scope, environment = self.fixture()
        guard = build.RustEnvironment(environment, scope)
        environment['TZ'] = 'changed'
        scope.receipt['declaredEnvironment'] = build.environment_material(environment, scope)
        with self.assertRaisesRegex(DependencyError, '^cargo-execution-environment-mutated$'):
            guard.check_unchanged(environment)
        with self.assertRaisesRegex(DependencyError, '^cargo-execution-environment-already-bound$'):
            build.RustEnvironment(environment, scope)

    def test_mutation_during_namespace_preparation_refuses_before_command(self):
        from unittest.mock import Mock
        from tools.application_dependency_store import DependencyError
        workspace, scope, environment = self.fixture()
        guard = build.RustEnvironment(environment, scope)
        actual_wrap = scope.wrap
        def changed(*args):
            command = actual_wrap(*args)
            environment['CARGO_BUILD_JOBS'] = '3'
            return command
        commands = Mock(environment=environment)
        with patch.object(scope, 'wrap', side_effect=changed), self.assertRaisesRegex(DependencyError, 'environment-mutated'):
            guard.compile(commands, scope.tools['cargo'], ['build'], workspace)
        commands.run.assert_not_called()

    def test_mutation_during_command_refuses_success_without_automatic_replay(self):
        from unittest.mock import Mock
        from tools.application_dependency_store import DependencyError
        workspace, scope, environment = self.fixture()
        guard = build.RustEnvironment(environment, scope)
        commands = Mock(environment=environment)
        def changed(*_args):
            environment['TZ'] = 'changed'
            return b'not an accepted build'
        commands.run.side_effect = changed
        with self.assertRaisesRegex(DependencyError, 'environment-mutated'):
            guard.compile(commands, scope.tools['cargo'], ['build'], workspace)
        commands.run.assert_called_once()

    def test_private_viewer_accepts_old_and_bound_receipts_and_refuses_raw_or_unknown_fields(self):
        import copy
        from tools.dev_workflow import executable_approval_request as viewer
        from tools.dev_workflow.common import DevError
        _workspace, scope, environment = self.fixture()
        self.assertIs(viewer._compiler(scope.receipt), scope.receipt)
        build.RustEnvironment(environment, scope)
        self.assertIs(viewer._compiler(scope.receipt), scope.receipt)
        for mutation in ('raw-value', 'unknown-variable', 'bool-size', 'foreign-tool'):
            value = copy.deepcopy(scope.receipt)
            selected = value['declaredEnvironment']
            if mutation == 'raw-value': selected['scalars']['LC_ALL']['value'] = 'private-' + 'marker'
            elif mutation == 'unknown-variable': selected['scalars']['UNSELECTED'] = None
            elif mutation == 'bool-size': selected['scalars']['TZ']['size'] = True
            else: selected['paths']['RUSTC'] = {'tool': 'cargo'}
            with self.subTest(mutation=mutation), self.assertRaisesRegex(DevError, '^executable-request-environment-invalid$'):
                viewer._compiler(value)


    def test_actual_builder_refuses_changed_environment_before_native_compile_boundary(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from tools import application_dependencies, captured_compiler_isolation, rust_application_dependencies
        from tools.application_dependency_store import DependencyError
        workspace, scope, _environment = self.fixture()
        root = workspace.parent
        source = project.create(root / 'source', 'greeting')
        pins = json.loads((source / 'sdk-lock.json').read_bytes())['toolchain']
        base_commands = build.Commands
        stages = []
        class ObservedCommands(base_commands):
            def run(self, stage, *_command):
                stages.append(stage)
                if stage == 'rust-sysroot':
                    return str(scope.distributions['rust-compiler-and-sysroot']).encode()
                if stage == 'zig-version':
                    return pins['sdk']['zig'].encode()
                if stage == 'bindgen-version':
                    return ('wit-bindgen-cli ' + pins['rust']['dependencies']['wit-bindgen']).encode()
                raise AssertionError('native compile boundary reached without stable declared environment')
        def isolate(owned, tools, distributions):
            scope.workspace, scope.tools, scope.distributions = owned.resolve(), tools, distributions
            scope.wrap = Mock(side_effect=AssertionError('changed environment reached namespace dispatch'))
            return scope
        def bindings(_work, _pins, commands, _tool):
            commands.environment['CARGO_BUILD_JOBS'] = '3'
            return project.digest(b'controlled bindings')
        closure = SimpleNamespace(lock={'selection': {'runtimeProfile': standard.DEFAULT}})
        verified = SimpleNamespace(lock={'executableInputs': [], 'transformations': [], 'artifacts': [],
            'selection': closure.lock['selection']})
        output = root / 'output'
        with patch.object(build, 'resolve_tools', return_value=(dict(scope.tools), [])), \
                patch.object(build.shutil, 'which', side_effect=lambda name, **_kwargs: str(scope.tools['shell' if name == 'sh' else name])), \
                patch.object(build, 'Commands', ObservedCommands), patch.object(build, 'binding_check', side_effect=bindings), \
                patch.object(application_dependencies, 'verify_inputs', return_value=verified), \
                patch.object(application_dependencies, 'prepare', return_value=closure), \
                patch.object(rust_application_dependencies, 'configure', return_value=(b'controlled manifest', {})), \
                patch.object(captured_compiler_isolation, 'Isolation', side_effect=isolate), \
                patch.object(build.guest_compatibility_build, 'failure_report'), \
                self.assertRaisesRegex(DependencyError, '^cargo-execution-environment-mutated$'):
            build.build(source, output, scope.tools['shell'], None, 'https://example.invalid/source')
        self.assertEqual(stages, ['rust-sysroot', 'zig-version', 'bindgen-version'])
        scope.wrap.assert_not_called()
        self.assertFalse((output / 'BUILD-COMPLETE.json').exists())
        failed = json.loads((output / 'BUILD-FAILED.json').read_bytes())
        self.assertEqual(failed['stage'], 'compile')
        self.assertEqual(failed['reason'], 'cargo-execution-environment-mutated')


class RustExecutableOutputMaterials(unittest.TestCase):
    """Approved output provenance controls; native commands remain mocked."""
    def fixture(self):
        temporary = tempfile.TemporaryDirectory(prefix='rust-output-control-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        target, output = root / 'target', root / 'output'
        target.mkdir(); output.mkdir()
        files = {'release/build/host/out/generated.rs': b'rs',
                 'wasm32-unknown-unknown/release/build/guest/out/asset.bin': b'abc',
                 'release/deps/libcontrolled.so': b'elf!'}
        for name, data in files.items():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        return target, output, files

    def test_valid_host_target_and_macro_outputs_keep_exact_bounded_identities(self):
        target, output, files = self.fixture()
        expected = {name: {'digest': project.digest(data), 'size': len(data)} for name, data in files.items()}
        guard = build.RustExecutableOutputs(target, output, project.digest(b'approval'))
        self.assertEqual(build.executable_output_inventory(target), expected)
        guard.check_unchanged()
        receipt = project.read_json(output / 'executable-input-outputs.json')
        self.assertEqual(receipt['outputs'], expected)
        self.assertEqual(receipt['approvalIdentity'], project.digest(b'approval'))
        self.assertFalse(receipt['hermetic'])
        self.assertNotIn(str(target), json.dumps(receipt))
        self.assertEqual(build.MAX_EXECUTABLE_OUTPUT_FILES, 8192)
        self.assertEqual(build.MAX_EXECUTABLE_OUTPUT_BYTES, 64 * 1024 * 1024)

    def test_existing_file_and_byte_caps_apply_jointly_to_all_output_roles(self):
        from tools.application_dependency_store import DependencyError
        target, _output, files = self.fixture()
        for field, maximum in [('MAX_EXECUTABLE_OUTPUT_FILES', 3), ('MAX_EXECUTABLE_OUTPUT_BYTES', 9)]:
            with self.subTest(field=field), patch.object(build, field, maximum):
                self.assertEqual(len(build.executable_output_inventory(target)), len(files))
            with self.subTest(over=field), patch.object(build, field, maximum - 1), \
                    self.assertRaisesRegex(DependencyError, '^captured build-tool generated output limit exceeded$'):
                build.executable_output_inventory(target)

    def test_empty_build_tool_output_directories_cannot_expand_discovery_without_bound(self):
        from tools.application_dependency_store import DependencyError
        target, _output, _files = self.fixture()
        (target / 'release/build/empty/out').mkdir(parents=True)
        with patch.object(build, 'MAX_EXECUTABLE_OUTPUT_FILES', 2), \
                self.assertRaisesRegex(DependencyError, 'generated output limit exceeded'):
            build.executable_output_inventory(target)

    def test_changed_removed_or_added_outputs_refuse_after_capture(self):
        from tools.application_dependency_store import DependencyError
        for mutation in ('changed', 'removed', 'added'):
            with self.subTest(mutation=mutation):
                target, output, _files = self.fixture()
                guard = build.RustExecutableOutputs(target, output, project.digest(b'approval'))
                selected = target / 'release/build/host/out/generated.rs'
                if mutation == 'changed': selected.write_bytes(b'changed')
                elif mutation == 'removed': selected.unlink()
                else: selected.with_name('additional.rs').write_bytes(b'added')
                with self.assertRaisesRegex(DependencyError, '^cargo-executable-outputs-mutated$'):
                    guard.check_unchanged()

    def test_receipt_rewrite_cannot_promote_changed_outputs(self):
        from tools.application_dependency_store import DependencyError
        target, output, _files = self.fixture()
        guard = build.RustExecutableOutputs(target, output, project.digest(b'approval'))
        (target / 'release/deps/libcontrolled.so').write_bytes(b'changed macro')
        receipt = project.read_json(guard.path)
        receipt['outputs'] = build.executable_output_inventory(target)
        guard.path.write_bytes(project.canonical(receipt))
        with self.assertRaisesRegex(DependencyError, '^cargo-executable-outputs-mutated$'):
            guard.check_unchanged()

    def test_missing_target_and_linked_ancestor_refuse_with_closed_failures(self):
        from tools import application_dependency_store as store
        from tools.application_dependency_store import DependencyError
        target, output, _files = self.fixture()
        with self.assertRaisesRegex(DependencyError, '^cargo-executable-outputs-unavailable$'):
            build.executable_output_inventory(target / 'absent')
        guard = build.RustExecutableOutputs(target, output, project.digest(b'approval'))
        with patch.object(store, 'is_reparse', side_effect=lambda path: path == target / 'release/build'), \
                self.assertRaisesRegex(DependencyError, '^cargo-executable-outputs-mutated$'):
            guard.check_unchanged()

    def test_actual_builder_refuses_late_generated_output_change_before_success(self):
        self.actual_builder(late_mutation=True)

    def test_actual_builder_preserves_valid_approved_output_and_success_path(self):
        self.actual_builder(late_mutation=False)

    def actual_builder(self, *, late_mutation):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from tools import application_dependencies, application_dependency_approval, captured_compiler_isolation
        from tools import rust_application_dependencies
        from tools.application_dependency_store import DependencyError
        workspace, scope, _environment = RustDeclaredEnvironment.fixture(self)
        source = project.create(workspace.parent / 'source', 'greeting')
        pins = json.loads((source / 'sdk-lock.json').read_bytes())['toolchain']
        base_commands, stages, outputs = build.Commands, [], []
        class ObservedCommands(base_commands):
            def run(self, stage, *command):
                stages.append(stage)
                if stage == 'rust-sysroot': return str(scope.distributions['rust-compiler-and-sysroot']).encode()
                if stage == 'zig-version': return pins['sdk']['zig'].encode()
                if stage == 'bindgen-version': return ('wit-bindgen-cli ' + pins['rust']['dependencies']['wit-bindgen']).encode()
                if stage == 'compile':
                    selected = Path(self.environment['CARGO_TARGET_DIR']) / 'release/build/controlled/out/generated.rs'
                    selected.parent.mkdir(parents=True); selected.write_bytes(b'original generated input')
                    outputs.append(selected)
                elif stage == 'contracts':
                    derived = Path(command[-1]); derived.mkdir()
                    for name in ('contracts.json', 'wit-lock.json'): (derived / name).write_bytes(b'{}')
                    (derived / 'surface.json').write_bytes(b'{"imports":[],"exports":[]}')
                elif stage != 'validate': raise AssertionError('unexpected native command: ' + stage)
                return b''
        def isolate(owned, tools, distributions):
            scope.workspace, scope.tools, scope.distributions = owned.resolve(), tools, distributions
            scope.wrap = Mock(return_value=['controlled native boundary'])
            scope.check_unchanged = Mock()
            return scope
        def prepare(_root, _work, output, _language, **_kwargs):
            project.write_json(output / 'application-dependencies.json', {'formatVersion': 1})
            return SimpleNamespace(lock={'selection': {'runtimeProfile': 'wasm32-unknown-unknown-panic-abort-v1'}},
                                   check_unchanged=Mock())
        def configure(_closure, work, _home):
            (work / 'Cargo.toml').write_bytes(b'controlled adapted manifest')
            return b'controlled adapted manifest', {}
        def componentize(_commands, _tool, _module, output, _source):
            (output / 'component.wasm').write_bytes(b'controlled component bytes')
            if late_mutation: outputs[0].write_bytes(b'changed after output inventory')
        def package(output, *_args): project.write_json(output / 'package-source.json', {'layers': []})
        verified = RustDeclaredEnvironment.verified(self)
        verified.lock['executableInputs'] = [{'id': 'outside/build-script'}]
        verified.lock['selection']['runtimeProfile'] = standard.DEFAULT
        output = workspace.parent / 'output'
        with patch.object(build, 'resolve_tools', return_value=(dict(scope.tools), [])), \
                patch.object(build.shutil, 'which', side_effect=lambda name, **_kwargs: str(scope.tools['shell' if name == 'sh' else name])), \
                patch.object(build, 'Commands', ObservedCommands), \
                patch.object(build, 'binding_check', return_value=project.digest(b'controlled bindings')), \
                patch.object(application_dependencies, 'verify_inputs', return_value=verified), \
                patch.object(application_dependencies, 'prepare', side_effect=prepare), \
                patch.object(application_dependency_approval, 'approve', return_value=SimpleNamespace(identity=project.digest(b'approval'))), \
                patch.object(rust_application_dependencies, 'configure', side_effect=configure), \
                patch.object(captured_compiler_isolation, 'Isolation', side_effect=isolate), \
                patch.object(build, 'componentize', side_effect=componentize), patch.object(build, 'package_inputs', side_effect=package), \
                patch.object(build.guest_compatibility_build, 'capture_host_recipe', side_effect=lambda _o, _r, inputs, _s: inputs), \
                patch.object(build.guest_compatibility_build, 'inspect'), patch.object(build.guest_compatibility_build, 'failure_report'), \
                patch.object(build.guest_runtime_receipts, 'emit', return_value={'name': 'runtime', 'digest': project.digest(b'runtime'), 'size': 7}), \
                patch.object(build.guest_compatibility_context_build, 'finish'):
            if late_mutation:
                with self.assertRaisesRegex(DependencyError, '^cargo-executable-outputs-mutated$'):
                    build.build(source, output, scope.tools['shell'], None, 'https://example.invalid/source',
                                executable_approval=project.digest(b'approval'))
            else:
                self.assertEqual(build.build(source, output, scope.tools['shell'], None, 'https://example.invalid/source',
                                            executable_approval=project.digest(b'approval')), output)
        self.assertEqual(stages, ['rust-sysroot', 'zig-version', 'bindgen-version', 'compile', 'validate', 'contracts'])
        self.assertEqual((output / 'BUILD-COMPLETE.json').exists(), not late_mutation)
        self.assertEqual((output / 'build-observation.json').exists(), not late_mutation)
        if late_mutation:
            failure = project.read_json(output / 'BUILD-FAILED.json')
            self.assertEqual(failure['stage'], 'recheck')
            self.assertEqual(failure['reason'], 'cargo-executable-outputs-mutated')
