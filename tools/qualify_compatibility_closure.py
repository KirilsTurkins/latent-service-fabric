"""Only the missing finite #679 cells on the ordinary selected SDK owners.

One language per bounded job. No guest compiler, engine or native host is built
by this controller except its ordinary selected application components. Native
products and the TS engine/splicer are separately fixed, normal-validated inputs.
Historical six-language qualification remains attributed to its original inputs.
"""
from __future__ import annotations

import argparse
import importlib
import re
from pathlib import Path
import subprocess
import sys
import time

if __package__ in {None, ''}: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import compatibility_api_fixture as fixtures
from tools import compatibility_api_managed_fixture as managed_fixture
from tools import compatibility_closure_node as node
from tools import compatibility_native_products as products
from tools import guest_api_analysis, guest_compatibility, guest_compatibility_context, guest_compiler_capture
from tools import guest_compiler_edges, guest_dependency_inputs
from tools import application_dependencies
from tools.build_observation import build_environment
from tools.dev_workflow.common import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, snapshot, write_json
from tools.run_rust_capsule_workflow import write_workflow_receipt

LANGUAGES = ('c', 'rust', 'go', 'java', 'dotnet', 'typescript')
CELLS = (*LANGUAGES, 'go-queues', 'typescript-initializer')
REPOSITORY = 'https://github.com/KirilsTurkins/latent-service-fabric'
PROGRAMME_SECONDS = 1800
CAPTURE_SECONDS = {'c': 600, 'rust': 3900, 'go': 4200, 'java': 600, 'dotnet': 2100,
    'typescript': 1800, 'go-queues': 4200, 'typescript-initializer': 1800}
JOB_MINUTES = {'c': 45, 'rust': 100, 'go': 105, 'java': 45, 'dotnet': 70,
    'typescript': 65, 'go-queues': 105, 'typescript-initializer': 65}


def prepare_java_cache(tools, output):
    """Explicit bounded normal compiler acquisition, before captured inputs.

    The one simple normal greeting warms the locked compiler dependencies.
    This is not a second application qualification or a native host build.
    """
    from tools.java_capsule_project import create
    from tools.java_guest.compiler import Compiler, read_only_dependency_cache, sdk_snapshot, tool_inventory
    started = time.monotonic(); deadline = started + 900
    output = fresh(Path(output))
    app = create(output / 'project', 'greeting')
    compiler = Compiler(output / 'compiler', Path(tools), timeout=900, _deadline=deadline)
    compiler.compile(app / 'src', app / 'wit', 'examples:greeting/service@1.0.0', output / 'compiled')
    compiler.check_unchanged()
    cache = read_only_dependency_cache(compiler.directory / 'gradle-home/caches/modules-2')
    require(time.monotonic() < deadline, 'compatibility-closure-normal-cache-prerequisite-deadline')
    record = {'schemaVersion': 'latent.compatibility.java-cache-prerequisite.v1', 'status': 'passed',
        'cache': 'compiler/gradle-home/caches/modules-2',
        'cacheInventoryDigest': digest(tool_inventory({'gradle-cache': cache})),
        'sdkIdentity': digest(inventory(sdk_snapshot(ROOT / 'sdk/java-guest'))),
        'compilerInputs': digest(compiler.compiler_inputs), 'commands': compiler.records,
        'maximumSeconds': 900, 'elapsedSeconds': time.monotonic() - started,
        'applicationRegistryResolution': False, 'nativeBuildCount': 0,
        'scope': 'normal-locked-compiler-greeting-prerequisite-only'}
    write_json(output / 'PREREQUISITE.json', record)
    return cache


def prepared_java_cache(path):
    from tools.java_guest.compiler import read_only_dependency_cache, sdk_snapshot, tool_inventory
    path = read_only_dependency_cache(Path(path))
    base = path.parents[3]
    value = read_json(base / 'PREREQUISITE.json', 1024**2)
    require(value['schemaVersion'] == 'latent.compatibility.java-cache-prerequisite.v1'
        and value['status'] == 'passed' and value['cache'] == path.relative_to(base).as_posix()
        and value['cacheInventoryDigest'] == digest(tool_inventory({'gradle-cache': path}))
        and value['sdkIdentity'] == digest(inventory(sdk_snapshot(ROOT / 'sdk/java-guest')))
        and value['maximumSeconds'] == 900 and value['elapsedSeconds'] < 900
        and value['applicationRegistryResolution'] is False and value['nativeBuildCount'] == 0,
        'compatibility-closure-source-bound-normal-cache-prerequisite')
    return path


def normal_build(language, app, output, native, tools, deadline, *, engine=None, read_only_cache=None,
                 _compiler_observer=None):
    require(language in LANGUAGES and deadline - time.monotonic() > 5,
        'compatibility-closure-original-compiler-deadline')
    args = (app, output, native['capsule_contracts'], native['package'], REPOSITORY)
    if language == 'c':
        from tools.c_capsule_build import build
        return build(*args, _deadline=deadline)
    if language == 'rust':
        from tools.rust_capsule_build import build
        return build(*args, _deadline=deadline)
    if language == 'go':
        from tools.go_capsule_build import build
        extra = {} if _compiler_observer is None else {'_compiler_observer': _compiler_observer}
        return build(*args, _deadline=deadline, **extra)
    if language == 'dotnet':
        from tools.dotnet_guest.build import build
        return build(*args, tools=tools, offline=True, _deadline=deadline)
    if language == 'java':
        from tools.java_capsule_build import build, FIBER_IO_PROFILE
        require(read_only_cache is not None, 'compatibility-closure-prepared-readonly-Java-cache')
        return build(*args, tools, timeout=min(900, deadline - time.monotonic() - 5),
            runtime_profile=FIBER_IO_PROFILE, read_only_cache=read_only_cache, _deadline=deadline)
    from tools.typescript_guest.build import build
    if engine is None:
        return build(*args, tools=tools, _deadline=deadline)
    return build(*args, tools=tools, runtime_engine=engine / 'engine/engine.wasm',
        runtime_engine_receipt=engine / 'engine/engine-input.json',
        runtime_splicer=engine / 'splicer/splicer', runtime_splicer_receipt=engine / 'splicer/splicer-input.json',
        _deadline=deadline)


def bound_analysis(artifact):
    raw = read_file(artifact / 'compatibility-report.json', 65536)
    report = guest_compatibility.read(raw)
    selected = guest_compatibility_context.read(read_file(artifact / 'compatibility-context.json', 65536), report=report)
    api = guest_api_analysis.read(read_file(artifact / guest_api_analysis.NAME, 65536), artifact, report, selected)
    complete = read_json(artifact / 'BUILD-COMPLETE.json')
    require(complete['packageAssembled'] is True
        and complete['observationDigest'] == digest(read_file(artifact / 'build-observation.json', 1024**2))
        and complete['componentDigest'] == report['componentDigest']
        and complete['sourceDigest'] == report['sourceDigest']
        and api['state'] == 'observed' and api['contextIdentity'] == selected['identity'],
        'compatibility-closure-normal-default-analysis-and-original-package')
    return {'report': report, 'context': selected, 'api': api,
        'component': file_identity(artifact / 'component.wasm', 64 * 1024**2)}


def capture(language, value):
    require(language in fixtures.LANGUAGES, 'compatibility-closure-fixed-transitive-capture')
    calls = []
    original = importlib.import_module('tools.' + language + '_capsule')
    def author(label, operation, app, *args):
        # In process: each original native owner retains its own child group,
        # cleanup and existing caps. No outer Python leader is killed first.
        require(operation in {'add', 'lock', 'resolve', 'review-lock', 'dependencies'}
            and len(calls) < (6 if language == 'go' else 4), 'compatibility-closure-fixed-capture-calls')
        result = original.main([operation, str(app), *map(str, args)])
        require(type(result) is int and result == 0, 'compatibility-closure-original-authoring-command')
        calls.append({'label': label, 'operation': operation, 'result': result})
    result = fixtures.capture(value, author)
    require(len(calls) == (6 if language == 'go' else 4), 'compatibility-closure-complete-original-capture')
    return {**result, 'normalMainCalls': calls, 'newProcessOwner': False}


def edge_pair(language, negative, positive, before, after, value):
    records = []
    for artifact in (negative, positive):
        observed = read_json(artifact / guest_compiler_capture.OUTPUT, 65536)
        guest_compiler_capture.validate(observed)
        matches = [row for row in observed['queries'] if row['source'] == value['rootSource']
            and row['root'] == value['rootFunction'] and row['callee'] == value['sourceTargetSpelling']]
        require(len(matches) == 1 and matches[0]['state'] == 'observed'
            and matches[0]['compilerTarget'] == value['targetFunction'],
            'compatibility-closure-actual-automatic-root-query')
        analysis = bound_analysis(artifact)
        joined = [row for row in analysis['api']['compilerFindings']['rows']
            if row['kind'] == 'compiler-call-edge' and row['queryIdentity'] == matches[0]['id']]
        require(len(joined) == 1 and joined[0]['rootMapping']['state'] == 'potential-root-path',
            'compatibility-closure-actual-final-root-mapping-required')
        records.append(matches[0]['observation'])
    return guest_compiler_edges.controlled_pair(records[0], records[1], before, after, value['rootSource'])


def capture_phase(cell, output, tools, *, read_only_cache=None):
    """Original normal native authors, before the fresh compiler phase clock.

    The allowance is checked after this fixed phase; it is not a new hard
    filesystem/process-owner theorem. Original child caps/cleanup remain exact.
    """
    from tools import compiler_compatibility_fixture as original
    from tools import compatibility_resource_fixture as resource
    started = time.monotonic(); deadline = started + CAPTURE_SECONDS[cell]
    language = 'go' if cell == 'go-queues' else 'typescript' if cell == 'typescript-initializer' else cell
    if cell in fixtures.LANGUAGES:
        value = fixtures.prepare(output / 'fixture', language)
        observed = capture(language, value); app = Path(value['projectPath'])
    elif cell == 'dotnet':
        value = managed_fixture.prepare(output / 'project'); app = value['projectPath']
        observed = managed_fixture.capture(app, output / 'outside', tools, deadline=deadline)
    elif cell == 'java':
        require(read_only_cache is not None, 'compatibility-closure-prepared-readonly-Java-cache')
        prepared_java_cache(read_only_cache)
        app = original.project('java', output / 'project'); value = {'projectPath': app}
        owner = Commands(ROOT, fresh(output / 'capture-commands'), build_environment(output),
            deadline_seconds=CAPTURE_SECONDS[cell], command_seconds=120)
        owner.deadline = min(owner.deadline, deadline - 5)
        observed = original.java_capture(app, output / 'outside', owner)
        observed = {**observed, 'originalCommandRecords': owner.records}
    elif cell == 'typescript':
        from tools import typescript_resource_runtime_fixture as normal
        app, value = resource.typescript(output / 'project', output / 'outside')
        observed = normal.capture(app, output / 'outside')
    elif cell == 'typescript-initializer':
        from tools import typescript_explicit_fallback_fixture as normal
        # The existing ordinary SYNC fixture owns its one complete native
        # capture. The following change is confined to the application root.
        app, observed = normal.project(output / 'project', output / 'outside')
        value = resource.typescript_initializer(app, observed)
    else:
        import shutil
        from tools import go_resource_runtime_fixture as normal
        from tools.go_guest.queues import PROFILE
        require(cell == 'go-queues', 'compatibility-closure-fixed-capture-cell')
        app, value = resource.go(output / 'project', output / 'outside')
        go = shutil.which('go'); require(go is not None, 'compatibility-closure-installed-normal-Go')
        observed = normal.capture(app, output / 'outside', Path(go), runtime_profile=PROFILE)
    elapsed = time.monotonic() - started
    require(elapsed < CAPTURE_SECONDS[cell], 'compatibility-closure-capture-allowance-consumed-no-compiler-start')
    accepted = application_dependencies.verify_inputs(app, language)
    require(accepted is not None, 'compatibility-closure-reviewed-transitive-inputs')
    return app, value, {'capture': observed, 'acceptedInputIdentity': accepted.identity,
        'elapsedSeconds': elapsed, 'allowanceSeconds': CAPTURE_SECONDS[cell],
        'normalOwnersUnchanged': True, 'compilerPhaseStarted': False}


def default_presentation(commands, artifact):
    # The ordinary report command receives no context/query/analysis selector;
    # it automatically authenticates and presents its normal sidecar.
    raw = commands.run('ordinary-default-compatibility-presentation', sys.executable, '-B',
        ROOT / 'tools/guest_compatibility.py', artifact / 'compatibility-report.json')
    require(b'API implementation observations;' in raw and len(raw) <= 1024**2,
        'compatibility-closure-normal-default-API-presentation')
    return {'sha256': digest(raw), 'bytes': len(raw), 'explicitAnalysisSelector': False}


def selected_go_body(captured, value, files, output):
    """Only the fixed public source fixture, never arbitrary captured app text."""
    require(value['language'] == 'go' and value['reached'] is False
        and value['rootFunction'] == 'compatibilityRoot'
        and files[value['rootSource']] == fixtures.application_source('go', reached=False)
        and captured.language == 'go' and captured.source_files == files
        and captured.selection == guest_compiler_capture.automatic(files, 'go'),
        'compatibility-Go-public-original-fixture-selection')
    matches = [row for row in captured.queries if row['source'] == value['rootSource']
        and row['root'] == value['rootFunction'] and row['callee'] == value['sourceTargetSpelling']]
    require(len(matches) == 1 and matches[0]['compilerTarget'] == value['targetFunction']
        and matches[0]['id'] not in captured.failures, 'compatibility-Go-exact-selected-query')
    query = matches[0]; raw = captured.raw.get(query['id'])
    require(type(raw) is bytes and 1 <= len(raw) <= 4096, 'compatibility-Go-public-body-byte-bound')
    rows = raw.decode('utf-8').splitlines()
    require('\0' not in raw.decode('utf-8') and 1 <= len(rows) <= 64
        and all(len(row.encode('utf-8')) <= 256 for row in rows), 'compatibility-Go-public-syntax-bound')
    tokens = []
    for number, row in enumerate(rows, 1):
        match = re.match(r'^\([?+\-0-9]+\) v[0-9]+ = ([A-Za-z0-9_]+)\b', row.strip())
        tokens.append({'line': number, 'text': row, 'opcode': None if match is None else match[1],
            'recognizedNonCallOpcode': None if match is None else match[1] in guest_compiler_edges.GO_PURE})
    destination = Path(output) / 'go-selected-body.ssa'
    require(not destination.exists() and not destination.is_symlink(), 'compatibility-Go-fresh-public-body')
    destination.write_bytes(raw)
    return {'scope': 'one-fixed-public-baseline-selected-compiler-body',
        'raw': {'bytes': len(raw), 'sha256': digest(raw)}, 'query': query,
        'sourceDigest': digest(inventory(files)), 'syntaxLines': tokens,
        'unrecognizedOpcodeTokens': sorted({row['opcode'] for row in tokens
            if row['recognizedNonCallOpcode'] is False and 'Call' not in row['opcode']}),
        'runtimeExecution': 'not-observed', 'qualificationClaimed': False}


def qualify(cell, native_directory, tools, output, *, engine=None, read_only_cache=None,
            go_selected_body_only=False):
    require(type(go_selected_body_only) is bool and (not go_selected_body_only or cell == 'go'),
        'compatibility-closure-fixed-Go-observation-selection')
    require(cell in CELLS and sys.platform == 'linux' and sys.version_info >= (3, 13),
        'compatibility-closure-linux-python313-closed-cell')
    language = 'go' if cell == 'go-queues' else 'typescript' if cell == 'typescript-initializer' else cell
    # Strict None refuses before acquisition, output or fallback to old hosts.
    reader = products.reader()
    require((engine is not None) == (cell == 'typescript')
        and (read_only_cache is not None) == (cell == 'java'),
        'compatibility-closure-unambiguous-prepared-compiler-selection')
    native_directory, tools = (Path(path).resolve(strict=True) for path in (native_directory, tools))
    compiled = reader.verify_prepared(native_directory)
    native_inputs = read_json(native_directory / 'source-inputs.json', 1024**2)
    native_preflight = products.current_source(native_inputs)
    current = native_preflight['currentSource']
    native = reader.native_products(native_directory)
    for path in native.values(): path.chmod(0o700)
    native_before = {name: file_identity(path, 512 * 1024**2) for name, path in native.items()}
    output = Path(output).absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents
        and all(output != path and output not in path.parents and path not in output.parents
            for path in (native_directory, tools)), 'compatibility-closure-separated-output')
    output = fresh(output)
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=10).decode().strip()
    record = {'schemaVersion': 'latent.compatibility.closure-language.v1', 'language': language, 'cell': cell,
        'status': 'incomplete', 'sourceCommit': head, 'native': compiled, 'nativeSource': current,
        'nativeSourcePreflight': native_preflight,
        'guestBuildCount': 0, 'nativeBuildCount': 0, 'runtimeQualificationFromGraph': False,
        'arbitraryApiSafety': 'unknown', 'wholeTicketComplete': False,
        'workflowJobMaximumMinutes': JOB_MINUTES[cell], 'captureAllowanceSeconds': CAPTURE_SECONDS[cell],
        'compilerNodePhaseMaximumSeconds': PROGRAMME_SECONDS, 'single1800SecondWholeProgrammeClaim': False}
    stage = 'original-normal-capture-phase'; commands = None
    try:
        app, value, record['capturePhase'] = capture_phase(cell, output, tools, read_only_cache=read_only_cache)
        commands = Commands(ROOT, fresh(output / 'commands'), build_environment(output),
            deadline_seconds=PROGRAMME_SECONDS, command_seconds=600)
        if cell == 'typescript':
            from tools.typescript_guest import borrow_signed_inputs
            require(engine is not None, 'compatibility-closure-normal-TS-products-required')
            engine = Path(engine).resolve(strict=True)
            record['engine'] = borrow_signed_inputs.verify(engine, commands.run)
        before = guest_dependency_inputs.capture_source(app, language).files
        observation = []
        def observe(captured):
            observation.append(selected_go_body(captured, value, before, output))
        stage = 'ordinary-default-component-and-selected-API-build'
        destination = output / ('build' if cell == 'java' else 'baseline')
        negative = normal_build(language, app, destination, native, tools, commands.deadline,
            engine=engine, read_only_cache=read_only_cache,
            **({'_compiler_observer': observe} if go_selected_body_only else {}))
        record['baseline'] = bound_analysis(negative); record['guestBuildCount'] += 1
        require(cell == 'typescript-initializer' or any(row['state'] == 'selected-implementation-unqualified'
            for row in record['baseline']['api']['apis']),
            'compatibility-closure-actual-owner-selected-implementation-not-all-unmapped')
        record['defaultPresentation'] = default_presentation(commands, negative)
        if go_selected_body_only:
            require(len(observation) == 1, 'compatibility-Go-one-original-compiler-observation')
            original = read_json(negative / guest_compiler_capture.OUTPUT, 65536)
            query = observation[0]['query']
            observed = [row for row in original['queries'] if row['id'] == query['id']]
            require(len(observed) == 1 and observed[0]['state'] == 'observed'
                and observed[0]['observation']['rawDigest'] == observation[0]['raw']['sha256']
                and observed[0]['observation']['rawBytes'] == observation[0]['raw']['bytes'],
                'compatibility-Go-original-body-observation-binding')
            record['goSelectedBody'] = {**observation[0], 'originalCompilerResult': original,
                'guestExecutionCount': 0, 'signedPackageCount': 0}
        elif cell == 'java':
            from tools.compiler_compatibility_observation import build_evidence
            from tools.qualify_compiler_compatibility import java_counterfactual
            from tools.compiler_compatibility_node import execute
            evidence = build_evidence(negative, language, before, record['capturePhase']['capture'])
            record['compilerPair'] = java_counterfactual(app, output, native, tools, read_only_cache,
                commands.deadline, record['capturePhase']['capture'])
            stage = 'original-Java-six-initializer-callback-outcomes'
            record['signed'] = execute(negative, native, output / 'node', commands.deadline, language, evidence)
        elif cell == 'typescript':
            stage = 'original-task-timer-operation-facts-and-fresh-stores'
            record['signed'] = node.execute(negative, native, output / 'node', commands.deadline,
                language, kind='typescript-resources')
        elif cell == 'typescript-initializer':
            stage = 'actual-SYNC-class-static-Unsupported-initialization-and-fresh-store'
            record['initializerSigned'] = node.execute(negative, native, output / 'initializer-node',
                commands.deadline, language, kind='api-pair', expected=value['expectedResult'])
            record['initializationScope'] = {'kind': value['initializationKind'], 'scope': value['expectedScope'],
                'initializerFailureClaimed': False, 'componentStartClaimed': False,
                'repeatInFreshStore': True, 'initializerExpectedCount': 1}
        elif cell == 'go-queues':
            stage = 'same-Go-component-original-eight-nine-queue-differential'
            record['signed'] = {str(ceiling): node.execute(negative, native, output / ('node-' + str(ceiling)),
                commands.deadline, language, kind='go-queues', queue_ceiling=ceiling) for ceiling in (8, 9)}
        else:
            expected = value['expectedResult'] if cell in fixtures.LANGUAGES else [{'ok': 'api|answer=42|fresh=1'}]
            record['baselineSigned'] = node.execute(negative, native, output / 'baseline-node', commands.deadline,
                language, kind='api-pair', expected=expected)
            stage = 'same-original-libraries-one-root-edge'
            if cell in fixtures.LANGUAGES: value = fixtures.counterfactual(value)
            else: managed_fixture.counterfactual(app)
            after = guest_dependency_inputs.capture_source(app, language).files
            require(application_dependencies.verify_inputs(app, language).identity == record['capturePhase']['acceptedInputIdentity'],
                'compatibility-closure-original-library-identity')
            positive = normal_build(language, app, output / 'reached', native, tools, commands.deadline)
            record['reached'] = bound_analysis(positive); record['guestBuildCount'] += 1
            if cell in fixtures.LANGUAGES:
                record['compilerPair'] = edge_pair(language, negative, positive, before, after, value)
                expected = value['expectedResult']
            else:
                record['compilerPair'] = guest_api_analysis.dotnet_retention_pair(
                    read_json(negative / 'compatibility-compiler-methods.json', 65536),
                    read_json(positive / 'compatibility-compiler-methods.json', 65536),
                    before, after, managed_fixture.ROOT_SOURCE)
            stage = 'actual-original-standard-api-fallback-and-fresh-invocation'
            record['reachedSigned'] = node.execute(positive, native, output / 'reached-node', commands.deadline,
                language, kind='api-pair', expected=expected)
            if cell in fixtures.LANGUAGES:
                stage = 'same-original-libraries-unsupported-initialization-and-fresh-store'
                value = fixtures.initializer(value)
                initialized = normal_build(language, app, output / 'initializer', native, tools, commands.deadline)
                record['initializer'] = bound_analysis(initialized); record['guestBuildCount'] += 1
                record['initializerSigned'] = node.execute(initialized, native, output / 'initializer-node',
                    commands.deadline, language, kind='api-pair', expected=value['expectedResult'])
                record['initializationScope'] = {'kind': value['initializationKind'],
                    'scope': value['expectedScope'], 'sourceAssertions': 'nativeUnsupported-and-initializerCount1',
                    'repeatInFreshStore': True, 'initializerFailureClaimed': False,
                    'beforeApplicationGreetingBody': language != 'rust', 'componentStartClaimed': False}
        require(reader.verify_prepared(native_directory) == compiled and products.current_source(native_inputs) == native_preflight
            and native_before == {name: file_identity(path, 512 * 1024**2) for name, path in native.items()}
            and subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=10).decode().strip() == head
            and time.monotonic() < commands.deadline, 'compatibility-closure-final-source-products-and-owner-budget')
        require(application_dependencies.verify_inputs(app, language).identity == record['capturePhase']['acceptedInputIdentity'],
            'compatibility-closure-final-accepted-inputs-unchanged')
        record.update(status='diagnostic-observed' if go_selected_body_only else 'passed', commands=commands.records)
        write_workflow_receipt(output / ('DIAGNOSTIC.json' if go_selected_body_only else 'qualified.json'), record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__,
            commands=[] if commands is None else commands.records)
        write_workflow_receipt(output / 'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cell', choices=CELLS)
    parser.add_argument('--prepare-java-cache', action='store_true')
    parser.add_argument('--go-selected-body-only', action='store_true')
    parser.add_argument('--native', type=Path)
    for name in ('tools', 'output'): parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--engine', type=Path)
    parser.add_argument('--read-only-cache', type=Path)
    args = parser.parse_args()
    if args.prepare_java_cache:
        require(args.cell is None and args.native is None and args.engine is None and args.read_only_cache is None
            and not args.go_selected_body_only,
            'compatibility-closure-unambiguous-normal-cache-prerequisite')
        print(prepare_java_cache(args.tools, args.output))
    else:
        require(args.cell in CELLS and args.native is not None, 'compatibility-closure-closed-owning-selection')
        print(qualify(args.cell, args.native, args.tools, args.output,
            engine=args.engine, read_only_cache=args.read_only_cache,
            go_selected_body_only=args.go_selected_body_only)['status'])
