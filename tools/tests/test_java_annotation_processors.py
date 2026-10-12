"""Real JAR/CAS/approval graph controls; headers never qualify JVM execution."""
import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import application_dependencies as inputs, java_annotation_processors as processors
from tools.application_dependency_approval import approve, request
from tools.application_dependency_store import DependencyError, Store
from tools.build_snapshot import canonical, digest
from tools.build_process import BuildProcessError
from tools.java_application_dependencies import classpath as application_classpath, deterministic_jar
from tools.java_dependency_authoring import current_application
from tools.java_dependency_resolution import declarations
from tools.java_resource_artifacts import capture_resources


class ProcessorCapture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='java-processor-graph-control-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / 'project'; self.project.mkdir()
        self.store = Store(self.project / 'dependency-inputs/objects')
        header = b'\xca\xfe\xba\xbe' + struct.pack('>HH', 0, 69) + b'header-control-only'
        self.payloads = {
            'unknown/application/1': deterministic_jar({'outside/App.class': header}),
            'unknown/shared/1': deterministic_jar({'outside/Shared.class': header,
                                                  'outside/shared.txt': b'original runtime resource'}),
            'unknown/leaf/1': deterministic_jar({'outside/Leaf.class': header}),
            'unknown/processor/1': deterministic_jar({'outside/Outer$Processor.class': header,
                'META-INF/services/javax.annotation.processing.Processor': b'outside.Outer$Processor\n',
                'processor-private.txt': b'executable tool resource'})}
        edges = {'unknown/application/1': ['unknown/shared/1'], 'unknown/shared/1': ['unknown/leaf/1'],
                 'unknown/leaf/1': [], 'unknown/processor/1': ['unknown/shared/1']}
        self.config = {'formatVersion': 1, 'dependencies': [], 'localJars': [],
            'repositories': [{'id': 'central', 'url': 'https://repo.maven.apache.org/maven2'}],
            'selection': {'release': 25, 'runtimeProfile': 'java-teavm-c'}}
        self.artifacts, self.identities, self.originals = [], {}, []
        for index, (identity, payload) in enumerate(self.payloads.items()):
            original = self.root / f'original-{index}.jar'; original.write_bytes(payload)
            self.originals.append(original)
            native = {'id': identity, 'path': '../' + original.name, 'dependencies': list(edges[identity])}
            if identity == 'unknown/processor/1':
                native['processorClasses'] = ['outside.Outer$Processor']
            self.config['localJars'].append(native)
            captured = self.store.put(payload); self.identities[identity] = captured
            self.artifacts.append({'id': identity, 'role': 'application', 'format': 'file',
                'mount': f'dependencies/java/{index:04d}.jar',
                'source': {'path': self.store.path(captured['digest']).relative_to(self.project).as_posix()},
                'dependencies': list(edges[identity]), 'metadata': {'ecosystem': 'captured-local-jar',
                    'scope': 'runtime', 'originalLocalPath': native['path']}})
        declarations(self.config)

    def capture(self, mutate=None):
        selected = copy.deepcopy(self.artifacts)
        processors.mark(self.config, selected)
        selected = capture_resources(self.project, self.store, selected)
        if mutate is not None:
            mutate(selected)
        config = canonical(self.config) + b'\n'
        native = {'formatVersion': 1, 'resolver': None, 'graph': [], 'artifacts': self.identities,
                  'configurationDigest': digest(config), 'selection': self.config['selection'],
                  'lifecycleScripts': 'disabled'}
        (self.project / 'java-dependencies.json').write_bytes(config)
        (self.project / 'java-resolved.lock.json').write_bytes(canonical(native))
        (self.project / inputs.MANIFEST).write_bytes(canonical({'formatVersion': 1, 'language': 'java',
            'selection': self.config['selection'], 'nativeLocks': ['java-dependencies.json', 'java-resolved.lock.json'],
            'artifacts': selected, 'transformations': []}))
        lock = inputs.capture(self.project)
        (self.project / inputs.LOCK).write_bytes(canonical(lock))
        return lock

    def prepared(self):
        lock = self.capture()
        verified = inputs.verify_inputs(self.project, 'java')
        isolation = Mock()
        isolation.workspace = self.root.resolve()
        isolation.receipt = {'profile': 'linux-captured-compiler-namespaces-v1',
                             'tools': {'compiler': digest(b'captured compiler model')}}
        specification = request(verified, isolation, digest(b'processor recipe model'))
        approved = approve(verified, isolation, digest(b'processor recipe model'), digest(canonical(specification)))
        work, output = self.root / 'work', self.root / 'output'; work.mkdir(); output.mkdir()
        closure = inputs.prepare(self.project, work, output, 'java', execution_approval=approved)
        return lock, closure, specification

    def test_shared_transitives_have_separate_approved_inputs_and_unchanged_runtime_owners(self):
        lock, _closure, specification = self.prepared()
        shared = {'unknown/shared/1', 'unknown/leaf/1'}
        self.assertEqual({row['id'] for row in specification['executableInputs']},
                         {'unknown/processor/1', *(processors.alias_id(identity) for identity in shared)})
        rows = {row['id']: row for row in lock['artifacts']}
        for identity in shared:
            original, executable = rows[identity], rows[processors.alias_id(identity)]
            self.assertEqual(original['role'], 'application')
            self.assertEqual(executable['role'], 'build-tool')
            self.assertEqual(original['original'], executable['original'])
            self.assertEqual(original['source'], executable['source'])
        self.assertIn('unknown/shared/1', rows['unknown/application/1']['dependencies'])
        self.assertIn(processors.alias_id('unknown/shared/1'), rows['unknown/processor/1']['dependencies'])
        self.assertIn(processors.alias_id('unknown/leaf/1'), rows[processors.alias_id('unknown/shared/1')]['dependencies'])
        self.assertEqual(processors.verify(self.config, lock['artifacts']),
                         [row for row in lock['artifacts'] if not processors.is_alias(row)])
        current_application(self.project, lock)

    def test_deleted_originals_use_captured_complete_processor_and_runtime_classpaths(self):
        _lock, closure, _specification = self.prepared()
        for original in self.originals:
            original.unlink()
        paths, names, receipt = processors.classpath(closure, self.root / 'processor-jars')
        self.assertEqual(names, ('outside.Outer$Processor',))
        self.assertEqual(len(paths), 3)
        self.assertFalse(receipt['automaticHostServiceDiscovery'])
        app, runtime = application_classpath(closure, self.root / 'application-jars')
        self.assertEqual(len(app), 3)
        self.assertEqual([item['path'] for item in runtime['resources']], ['outside/shared.txt'])
        self.assertFalse(any('processor-private' in row['path'] for row in runtime['resources']))
        closure.check_unchanged()

    def test_unapproved_processor_graph_cannot_materialize_or_execute(self):
        self.capture()
        work, output = self.root / 'work', self.root / 'output'; work.mkdir(); output.mkdir()
        with self.assertRaisesRegex(DependencyError, 'executable'):
            inputs.prepare(self.project, work, output, 'java')
        self.assertFalse(list(work.rglob('*.jar')))

    def test_runtime_and_processor_selection_cannot_share_the_processor_root(self):
        self.artifacts[0]['dependencies'].append('unknown/processor/1')
        with self.assertRaisesRegex(DependencyError, 'also-selected-as-runtime-root'):
            processors.mark(self.config, self.artifacts)

    def test_uncaptured_processor_class_is_a_static_denial(self):
        self.config['localJars'][-1]['processorClasses'] = ['unknown.Uncaptured']
        _lock, closure, _specification = self.prepared()
        with self.assertRaisesRegex(DependencyError, 'class-not-captured'):
            processors.classpath(closure, self.root / 'processor-jars')

    def test_changed_explicit_class_selection_invalidates_the_native_candidate(self):
        lock = self.capture()
        changed = copy.deepcopy(self.config); changed['localJars'][-1]['processorClasses'] = ['outside.Other']
        (self.project / 'java-dependencies.json').write_bytes(canonical(changed))
        with self.assertRaisesRegex(DependencyError, 'native-graph-or-declaration-drift'):
            current_application(self.project, lock)

    def test_removed_alias_and_unaliased_executable_edge_are_rejected(self):
        lock = self.capture()
        alias = processors.alias_id('unknown/shared/1')
        changed = copy.deepcopy(lock['artifacts']); changed = [row for row in changed if row['id'] != alias]
        with self.assertRaisesRegex(DependencyError, 'graph-not-closed'):
            processors.verify(self.config, changed)
        changed = copy.deepcopy(lock['artifacts'])
        next(row for row in changed if row['id'] == 'unknown/processor/1')['dependencies'] = ['unknown/shared/1']
        with self.assertRaisesRegex(DependencyError, 'declaration-drift'):
            processors.verify(self.config, changed)

    def test_alias_owner_role_mount_bytes_and_metadata_cannot_drift(self):
        lock = self.capture()
        mutations = [lambda row: row.update(role='application'),
                     lambda row: row.update(mount='dependencies/elsewhere.jar'),
                     lambda row: row['original'].update(digest=digest(b'changed')),
                     lambda row: row['files'][0].update(size=row['files'][0]['size'] + 1),
                     lambda row: row['metadata'].update(profile='unqualified'),
                     lambda row: row['metadata'].update(originalArtifact='unknown/application/1')]
        for change in mutations:
            changed = copy.deepcopy(lock['artifacts'])
            change(next(row for row in changed if row['id'] == processors.alias_id('unknown/shared/1')))
            with self.subTest(change=change), self.assertRaises(DependencyError):
                processors.verify(self.config, changed)

    def test_alias_capture_is_deterministic_without_library_catalogues(self):
        first = copy.deepcopy(self.artifacts); second = copy.deepcopy(self.artifacts)
        processors.mark(self.config, first); processors.mark(self.config, second)
        self.assertEqual(first, second)
        self.assertEqual(len([row for row in first if processors.is_alias(row)]), 2)

    def test_duplicate_capture_alias_and_missing_graph_input_are_denied(self):
        changed = copy.deepcopy(self.artifacts); changed.append(copy.deepcopy(changed[0]))
        with self.assertRaisesRegex(DependencyError, 'ambiguous-or-limit'):
            processors.mark(self.config, changed)
        changed = copy.deepcopy(self.artifacts)
        collision = copy.deepcopy(changed[0]); collision['id'] = processors.alias_id('unknown/shared/1')
        changed.append(collision)
        with self.assertRaisesRegex(DependencyError, 'artifact-collision'):
            processors.mark(self.config, changed)
        changed = copy.deepcopy(self.artifacts); changed[-1]['dependencies'].append('uncaptured/library')
        with self.assertRaisesRegex(DependencyError, 'graph-not-closed'):
            processors.mark(self.config, changed)

    def test_reselection_or_extra_executable_alias_is_denied(self):
        marked = copy.deepcopy(self.artifacts); processors.mark(self.config, marked)
        with self.assertRaisesRegex(DependencyError, 'already-selected'):
            processors.mark(self.config, marked)
        lock = self.capture(); changed = copy.deepcopy(lock['artifacts'])
        row = copy.deepcopy(next(row for row in changed if processors.is_alias(row)))
        row.update(id=processors.alias_id('unknown/application/1'))
        row['metadata']['originalArtifact'] = 'unknown/application/1'; changed.append(row)
        with self.assertRaisesRegex(DependencyError, 'alias-graph-drift'):
            processors.verify(self.config, changed)

    def test_processor_helper_is_explicitly_captured_without_becoming_a_runtime_root(self):
        rows = {row['id']: row for row in self.config['localJars']}
        rows['unknown/leaf/1']['processorInput'] = True
        rows['unknown/shared/1']['dependencies'] = []
        rows['unknown/processor/1']['dependencies'].append('unknown/leaf/1')
        for artifact in self.artifacts:
            artifact['dependencies'] = list(rows[artifact['id']]['dependencies'])
        lock, closure, specification = self.prepared()
        captured = {row['id']: row for row in lock['artifacts']}
        self.assertEqual(captured['unknown/leaf/1']['role'], 'build-tool')
        self.assertEqual(captured['unknown/leaf/1']['metadata']['processorClasses'], [])
        self.assertIn('unknown/leaf/1', {row['id'] for row in specification['executableInputs']})
        _paths, selection = application_classpath(closure, self.root / 'runtime-helper-control')
        self.assertNotIn('unknown/leaf/1', {row['id'] for row in selection['artifacts']})
        self.assertFalse(any(row['metadata'].get('owner') == 'unknown/leaf/1'
                             for row in lock['artifacts']))
        current_application(self.project, lock)

    def test_unreachable_processor_input_cannot_enter_an_execution_receipt(self):
        row = self.config['localJars'][0]
        row['processorInput'] = True
        with self.assertRaisesRegex(DependencyError, 'java-annotation-processor-input-not-reachable'):
            self.capture()
        self.assertFalse((self.project / inputs.LOCK).exists())

    def test_processor_input_declaration_has_one_exact_role(self):
        row = self.config['localJars'][0]
        for flag in (False, 1, 'true', None):
            with self.subTest(flag=flag):
                candidate = copy.deepcopy(self.config)
                candidate['localJars'][0]['processorInput'] = flag
                with self.assertRaises(DependencyError):
                    declarations(candidate)
        row['processorInput'] = True
        row['processorClasses'] = ['outside.Outer$Processor']
        with self.assertRaises(DependencyError):
            declarations(self.config)

    def test_duplicate_or_oversized_processor_class_selection_is_denied(self):
        for selected in ([], ['a.A', 'a.A'], ['bad/path.Class'], ['a.' + 'x' * 257], ['p.C' + str(i) for i in range(33)], ['a.\u2603']):
            with self.subTest(selected=selected), self.assertRaises(DependencyError):
                processors.classes(selected)
        self.assertEqual(processors.classes(['outside.Outer$Processor']), ('outside.Outer$Processor',))


class ProcessorStage(unittest.TestCase):
    """Exercise the parent stage; mocked commands do not prove containment."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='java-processor-stage-control-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.index = 0

    def fixture(self):
        self.index += 1
        root = self.root / str(self.index); root.mkdir()
        workspace = root / 'workspace'; workspace.mkdir()
        (workspace / 'inputs').mkdir()
        source = root / 'java/outside'; source.mkdir(parents=True)
        (source / 'App.java').write_bytes(b'package outside; public class App {}\n')
        compiler_dir = root / 'compiler'; compiler_dir.mkdir()
        sdk = root / 'sdk/processors'; sdk.mkdir(parents=True)
        control = Path(__file__).resolve().parents[2] / 'sdk/java-guest/processors/SourceOwnership.java'
        (sdk / 'SourceOwnership.java').write_bytes(control.read_bytes())
        compiler = SimpleNamespace(directory=compiler_dir, sdk=sdk.parent, records=[], retained_bytes=0,
                                   deadline=time.monotonic() + 45, environment={'LANG': 'C.UTF-8'})
        isolated = Mock()
        isolated.workspace = workspace
        isolated.receipt = {'profile': 'captured-stage-control-only'}
        isolated.tools = {'javac': Path('/captured/javac'), 'java': Path('/captured/java')}
        isolated.wrap.side_effect = lambda tool, arguments, _cwd, _environment: [str(tool), *arguments]
        output = workspace / 'outputs'
        stage = (isolated, (workspace / 'inputs/processor.jar',), ('outside.ExplicitProcessor',), output, ())
        return compiler, source.parent, output, isolated, stage

    def execute(self, fixture, command):
        compiler, source, _output, _isolated, stage = fixture
        with patch.object(processors, 'run_bounded_result', side_effect=command):
            return processors.process(compiler, source, ('outside/App.java',), source.parent, stage, ())

    def test_only_explicit_processors_and_new_source_enter_the_compilation(self):
        fixture = self.fixture(); compiler, source, output, isolated, _stage = fixture
        calls = []
        generated = b'package outside; public class Generated { public static int value() { return 42; } }\n'
        def command(argv, cwd, environment, deadline, bound):
            calls.append((argv, cwd, environment, deadline, bound))
            if argv[0].endswith('javac'):
                target = output / 'generated/outside/Generated.java'; target.parent.mkdir(); target.write_bytes(generated)
                return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
            return SimpleNamespace(returncode=0, stdout=b'SOURCE-OWNERSHIP-OK\n', stderr=b'')
        receipt = self.execute(fixture, command)
        self.assertEqual((source / 'outside/Generated.java').read_bytes(), generated)
        self.assertEqual(receipt['generated'], {'outside/Generated.java': {'digest': digest(generated), 'size': len(generated)}})
        self.assertIn('-proc:only', calls[0][0])
        self.assertEqual(calls[0][0][calls[0][0].index('-processor') + 1], 'outside.ExplicitProcessor')
        self.assertEqual(calls[0][0][calls[0][0].index('-classpath') + 1],
                         str(isolated.workspace / 'inputs/processor.jar'))
        self.assertIn('--source', calls[1][0])
        self.assertLessEqual(calls[1][3], calls[0][3])
        self.assertLessEqual(calls[0][3], 45)
        self.assertTrue(all(row[4] == 1024 * 1024 for row in calls))
        self.assertEqual([row['stage'] for row in compiler.records], ['annotation-processors', 'processor-source-ownership'])
        self.assertTrue(all(row['cleanup'] == 'reaped' for row in compiler.records))
        isolated.protect_inputs.assert_any_call(output / 'generated')
        self.assertEqual(receipt['sourceOwnershipControl']['profile'], 'pinned-javac-ast-parse-only-v1')

    def test_processor_nonzero_is_retained_without_promoting_untrusted_diagnostics(self):
        fixture = self.fixture(); compiler, source, _output, _isolated, _stage = fixture
        secret = b'untrusted private diagnostic marker'
        with self.assertRaisesRegex(DependencyError, '^java-annotation-processor-stage-failed$'):
            self.execute(fixture, lambda *_args: SimpleNamespace(returncode=9, stdout=b'', stderr=secret))
        self.assertEqual(len(compiler.records), 1)
        self.assertEqual(compiler.records[0]['exitCode'], 9)
        self.assertEqual((compiler.directory / '0-annotation-processors.log').read_bytes(), b'\n' + secret)
        self.assertEqual(list(source.rglob('*.java')), [source / 'outside/App.java'])

    def test_class_output_does_not_enter_the_guest(self):
        fixture = self.fixture(); _compiler, source, output, _isolated, _stage = fixture
        def command(*_args):
            (output / 'classes/Unreviewed.class').write_bytes(b'unqualified class output')
            return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
        with self.assertRaisesRegex(DependencyError, 'bytecode-output-unqualified'):
            self.execute(fixture, command)
        self.assertEqual(list(source.rglob('*.java')), [source / 'outside/App.java'])

    def test_unqualified_sibling_outputs_do_not_become_parent_validation_inputs(self):
        for name in ('source-ownership.inputs', 'child-report.json'):
            fixture = self.fixture(); compiler, source, output, _isolated, _stage = fixture
            untrusted = b'untrusted executable output remains unchanged'
            def command(*_args):
                (output / name).write_bytes(untrusted)
                return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
            with self.subTest(name=name), self.assertRaisesRegex(DependencyError, 'unqualified-output'):
                self.execute(fixture, command)
            self.assertEqual((output / name).read_bytes(), untrusted)
            self.assertEqual(len(compiler.records), 1)
            self.assertEqual(list(source.rglob('*.java')), [source / 'outside/App.java'])

    def test_precreated_validation_link_cannot_overwrite_an_outside_workspace_witness(self):
        fixture = self.fixture(); compiler, source, output, _isolated, _stage = fixture
        witness = self.root / 'unrelated-host-witness'
        original = b'host file must never become an executable-stage output'
        witness.write_bytes(original)
        def command(*_args):
            os.link(witness, output / 'source-ownership.inputs')
            return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
        with self.assertRaisesRegex(DependencyError, 'unqualified-output'):
            self.execute(fixture, command)
        self.assertEqual(witness.read_bytes(), original)
        self.assertEqual(len(compiler.records), 1)
        self.assertEqual(list(source.rglob('*.java')), [source / 'outside/App.java'])

    def test_invalid_encoding_existing_source_and_non_source_outputs_are_rejected(self):
        for name, data, code in [('outside/App.java', b'changed', 'collision-or-kind'),
                                  ('outside/generated.txt', b'not source', 'collision-or-kind'),
                                  ('outside/Generated.java', b'\xff\xfe', 'source-encoding')]:
            fixture = self.fixture(); _compiler, source, output, _isolated, _stage = fixture
            def command(*_args):
                target = output / 'generated' / name; target.parent.mkdir(); target.write_bytes(data)
                return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
            with self.subTest(name=name), self.assertRaisesRegex(DependencyError, code):
                self.execute(fixture, command)
            self.assertEqual((source / 'outside/App.java').read_bytes(), b'package outside; public class App {}\n')

    def test_readonly_source_mutation_is_detected_before_generated_source_is_copied(self):
        fixture = self.fixture(); _compiler, source, _output, isolated, _stage = fixture
        def command(*_args):
            (isolated.workspace / 'inputs/processor-sources/outside/App.java').write_bytes(b'changed')
            return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
        with self.assertRaisesRegex(DependencyError, 'readonly-input-mutated'):
            self.execute(fixture, command)
        self.assertEqual((source / 'outside/App.java').read_bytes(), b'package outside; public class App {}\n')

    def test_owner_denial_cannot_install_generated_sources(self):
        fixture = self.fixture(); compiler, source, output, _isolated, _stage = fixture
        def command(argv, *_args):
            if argv[0].endswith('javac'):
                target = output / 'generated/outside/Generated.java'; target.parent.mkdir()
                target.write_bytes(b'package java.lang; class Unreviewed {}\n')
                return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
            return SimpleNamespace(returncode=1, stdout=b'', stderr=b'java-annotation-processor-generated-source-overrides-platform\n')
        with self.assertRaisesRegex(DependencyError, 'generated-source-owner-denied'):
            self.execute(fixture, command)
        self.assertEqual(len(compiler.records), 2)
        self.assertFalse((source / 'outside/Generated.java').exists())

    def test_original_command_failures_preserve_confirmed_and_unconfirmed_cleanup(self):
        for reason, cleanup in [('command-deadline', 'reaped'), ('command-output-limit', 'reaped'),
                                ('process-cleanup', 'unconfirmed')]:
            fixture = self.fixture(); compiler, source, _output, _isolated, _stage = fixture
            def command(*_args):
                raise BuildProcessError(reason)
            with self.subTest(reason=reason), self.assertRaisesRegex(BuildProcessError, reason):
                self.execute(fixture, command)
            self.assertEqual(compiler.records[0]['processFailure'], reason)
            self.assertEqual(compiler.records[0]['cleanup'], cleanup)
            self.assertFalse((source / 'outside/Generated.java').exists())

    def test_generated_source_mutation_after_owner_check_is_rejected(self):
        fixture = self.fixture(); _compiler, source, output, _isolated, _stage = fixture
        def command(argv, *_args):
            target = output / 'generated/outside/Generated.java'
            if argv[0].endswith('javac'):
                target.parent.mkdir(); target.write_bytes(b'package outside; class Generated {}\n')
                return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
            target.write_bytes(b'changed after validation')
            return SimpleNamespace(returncode=0, stdout=b'SOURCE-OWNERSHIP-OK\n', stderr=b'')
        with self.assertRaisesRegex(DependencyError, 'input-or-output-mutated'):
            self.execute(fixture, command)
        self.assertFalse((source / 'outside/Generated.java').exists())


class ProcessorAuthoring(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='java-processor-authoring-control-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / 'application'
        from tools.java_capsule_project import create
        create(self.project, 'greeting', 'processor-authoring-control')
        self.sdk = (self.project / 'sdk-lock.json').read_bytes()
        header = b'\xca\xfe\xba\xbe' + struct.pack('>HH', 0, 69) + b'header-control-only'
        self.processor = self.root / 'outside-processor.jar'
        self.processor.write_bytes(deterministic_jar({'unknown/Processor.class': header}))
        self.helper = self.root / 'outside-helper.jar'
        self.helper.write_bytes(deterministic_jar({'unknown/Helper.class': header}))

    def cli(self, *arguments):
        from tools.java_capsule import main
        with redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()) as stderr:
            code = main([str(argument) for argument in arguments])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_actual_cli_reviews_a_local_processor_and_helper_without_running_a_jvm(self):
        helper = 'developer-owned-unknown-helper/7'
        processor = 'developer-owned-unknown-processor/13'
        self.assertEqual(self.cli('add-local', self.project, '--id', helper,
                                 '--jar', self.helper, '--processor-input')[0], 0)
        self.assertEqual(self.cli('add-local', self.project, '--id', processor,
                                 '--jar', self.processor, '--depends', helper,
                                 '--processor-class', 'unknown.Processor')[0], 0)
        candidate = self.root / 'reviewed-processors.json'
        with patch('tools.java_dependency_resolution.run_bounded_result',
                   side_effect=AssertionError('local-only capture must never start a JVM')):
            self.assertEqual(self.cli('resolve', self.project, '--candidate', candidate)[0], 0)
        self.assertFalse((self.project / inputs.LOCK).exists())
        identity = digest(candidate.read_bytes())
        self.assertEqual(self.cli('review-lock', self.project, '--candidate', candidate, '--expect', identity)[0], 0)
        verified = inputs.verify_inputs(self.project, 'java')
        self.assertEqual(set(verified.lock['executableInputs']), {helper, processor})
        by_id = {row['id']: row for row in verified.lock['artifacts']}
        self.assertEqual(by_id[processor]['dependencies'], [helper])
        self.assertEqual(by_id[processor]['metadata']['processorClasses'], ['unknown.Processor'])
        self.assertEqual(by_id[helper]['metadata']['processorClasses'], [])
        self.assertEqual((self.project / 'sdk-lock.json').read_bytes(), self.sdk)
        self.processor.unlink(); self.helper.unlink()
        self.assertEqual(self.cli('dependencies', self.project)[0], 0)
        with self.assertRaisesRegex(DependencyError, '^dependency-executable-tools-require-isolated-stage$'):
            work = self.root / 'unapproved-work'; work.mkdir()
            output = self.root / 'unapproved-output'; output.mkdir()
            inputs.prepare(self.project, work, output, 'java')

    def test_conflicting_helper_and_processor_roles_leave_all_reviewed_inputs_unchanged(self):
        code, _stdout, stderr = self.cli('add-local', self.project, '--id', 'unknown-conflicting-input',
            '--jar', self.processor, '--processor-input', '--processor-class', 'unknown.Processor')
        self.assertEqual(code, 1)
        self.assertIn('java-annotation-processor-input-and-class-selection-conflict', stderr)
        self.assertFalse((self.project / 'java-dependencies.json').exists())
        self.assertFalse((self.project / inputs.LOCK).exists())
        self.assertEqual((self.project / 'sdk-lock.json').read_bytes(), self.sdk)

    def test_reviewed_in_application_processor_bytes_are_passive_until_exact_execution_approval(self):
        from tools.java_capsule_project import validate
        from tools.rust_capsule_project import snapshot
        selected = self.project / 'reviewed-source-processor.jar'
        selected.write_bytes(self.processor.read_bytes())
        identity = 'developer-owned-in-application-processor/2'
        self.assertEqual(self.cli('add-local', self.project, '--id', identity, '--jar', selected,
                                 '--processor-class', 'unknown.Processor')[0], 0)
        candidate = self.root / 'in-application-processor-candidate.json'
        with patch('tools.java_dependency_resolution.run_bounded_result',
                   side_effect=AssertionError('passive local capture must never start a JVM')):
            self.assertEqual(self.cli('resolve', self.project, '--candidate', candidate)[0], 0)
        self.assertEqual(self.cli('review-lock', self.project, '--candidate', candidate,
                                 '--expect', digest(candidate.read_bytes()))[0], 0)
        reviewed = snapshot(self.project)
        validate(reviewed)
        self.assertEqual((self.project / 'sdk-lock.json').read_bytes(), self.sdk)
        changed = dict(reviewed)
        changed[selected.name] = deterministic_jar({'unknown/Changed.class': b'changed unreviewed input'})
        with self.assertRaisesRegex(ValueError, 'uncaptured Java binary dependencies'):
            validate(changed)
        verified = inputs.verify_inputs(self.project, 'java')
        self.assertEqual(verified.lock['executableInputs'], [identity])
        with self.assertRaisesRegex(DependencyError, '^dependency-executable-tools-require-isolated-stage$'):
            work = self.root / 'passive-unapproved-work'; work.mkdir()
            output = self.root / 'passive-unapproved-output'; output.mkdir()
            inputs.prepare(self.project, work, output, 'java')


class ProcessorFrontend(unittest.TestCase):
    def test_exact_java_approval_is_forwarded_once_through_the_selected_frontend(self):
        from tools import dev_guest_recipe as frontend
        marker = digest(b'explicit exact executable closure approval')
        stdout = SimpleNamespace(buffer=io.BytesIO())
        argv = ['dev_guest_recipe.py', '--language', 'java', '--project', '/owned/app',
                '--output', '/owned/output', '--executable-approval', marker]
        with patch.object(sys, 'argv', argv), patch.object(sys, 'stdout', stdout), \
                patch.object(frontend, 'compile_managed') as managed, \
                patch.object(frontend, 'compile_rust') as rust, patch.object(frontend, 'diagnostics'):
            self.assertEqual(frontend.main(), 0)
        managed.assert_called_once()
        self.assertEqual(managed.call_args.args[-1], 'java')
        self.assertEqual(managed.call_args.kwargs, {'executable_approval': marker})
        rust.assert_not_called()
        result = json.loads(stdout.buffer.getvalue())
        self.assertEqual(result['code'], 'success')
        self.assertEqual(result['schemaVersion'], 'latent.dev.compiler-result.v1')

    def test_invalid_or_unimplemented_frontend_approval_never_dispatches_a_compiler(self):
        from tools import dev_guest_recipe as frontend
        for language, marker in [('java', 'not-a-captured-identity'), ('go', digest(b'valid but unsupported'))]:
            stdout = SimpleNamespace(buffer=io.BytesIO())
            argv = ['dev_guest_recipe.py', '--language', language, '--project', '/owned/app',
                    '--output', '/owned/output', '--executable-approval', marker]
            with self.subTest(language=language), patch.object(sys, 'argv', argv), \
                    patch.object(sys, 'stdout', stdout), redirect_stderr(io.StringIO()), \
                    patch.object(frontend, 'compile_managed') as managed, \
                    patch.object(frontend, 'compile_rust') as rust, patch.object(frontend, 'diagnostics'):
                self.assertEqual(frontend.main(), 1)
            managed.assert_not_called(); rust.assert_not_called()
            self.assertEqual(json.loads(stdout.buffer.getvalue())['code'], 'compiler-input-or-build-failed')

    def test_managed_java_consumer_keeps_the_approval_and_selected_offline_cache(self):
        from tools import dev_guest_recipe as frontend
        with tempfile.TemporaryDirectory(prefix='processor-managed-consumer-') as directory:
            root = Path(directory)
            project = root / 'app'; project.mkdir()
            (root / 'build-cache').mkdir()
            payload, output, staged = root / 'payload', root / 'output', root / 'captured-managed'
            marker = digest(b'captured input approval')
            check = Mock()
            with patch.object(sys, 'platform', 'linux'), patch.object(frontend.platform, 'machine', return_value='x86_64'), \
                    patch.dict(os.environ), patch('tools.dev_managed_tools.unpack', return_value=staged) as unpack, \
                    patch('tools.java_capsule_build.build') as build:
                frontend.compile_managed(payload, project, output, check, 'java', executable_approval=marker)
            unpack.assert_called_once_with(payload / 'sdk', root / 'build-cache/managed', check)
            build.assert_called_once()
            self.assertEqual(build.call_args.kwargs['executable_approval'], marker)
            self.assertEqual(build.call_args.kwargs['offline_cache'], staged / 'gradle-cache')
            self.assertEqual(build.call_args.kwargs['gradle'], str(staged / 'gradle/bin/gradle'))
            self.assertEqual(build.call_args.args[-1], staged / 'wasi-sdk')
            check.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
