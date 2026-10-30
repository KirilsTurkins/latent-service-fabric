"""One substantive signed diagnostics fixture, with opt-in compiler observation.

Java additionally selects the exact same captured native declaration through one
root edge and requires the actual compiler's closed refusal. No graph is treated
as execution and no application code is run in the compiler host.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import time

if __package__ in {None, ''}: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import activation_stack_native_products as products
from tools.activation_stack_native_source import assert_current
from tools import application_dependencies as inputs
from tools import guest_compatibility as compatibility
from tools import compiler_compatibility_fixture as fixture
from tools.compiler_compatibility_node import execute
from tools.compiler_compatibility_observation import build_evidence
from tools.build_observation import build_environment
from tools.java_capsule_build import build as java_build, FIBER_IO_PROFILE, RECIPE as JAVA_RECIPE
from tools.dotnet_guest.build import build as dotnet_build, RECIPE as DOTNET_RECIPE
from tools.dotnet_guest.compiler import runtime_inputs
from tools.java_standard_http_library import compiler_cache
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, snapshot, write_json
from tools.run_rust_capsule_workflow import write_workflow_receipt

REPOSITORY = 'https://github.com/KirilsTurkins/latent-service-fabric'
MATERIALS = tuple(sorted(set((*JAVA_RECIPE, *DOTNET_RECIPE,
    'tools/qualify_compiler_compatibility.py', 'tools/compiler_compatibility_fixture.py',
    'tools/compiler_compatibility_observation.py', 'tools/compiler_compatibility_node.py',
    'tools/activation_stack_native_products.py', 'tools/activation_stack_native_source.py',
    'tools/sdk_native_products_reader.py', 'tools/java_replay_materials.py',
    'tools/java_standard_http_library.py', 'tools/java_resource_runtime_node.py',
    'tools/java_http_release_preparation.py', 'tools/resource_tenant_node.py', 'tools/resource_runtime_node.py',
    'tools/qualify_resource_tenants.py', 'tools/qualify_sdk_scratch.py', 'tools/rust_capsule_node.py',
    'tools/rust_capsule_build.py', 'tools/rust_capsule_project.py', 'tools/run_rust_capsule_workflow.py',
    'tools/phase2_operator_process.py', 'tools/phase2_operator_scenario.py', 'tools/phase3_resource_identity.py',
    'tools/phase3_resource_os.py', 'tools/phase3_resource_profile.py', 'tools/sdk_provider_scenario.py',
    'tools/build_observation.py', 'tools/build_process_signals.py', 'tools/guest_runtime_receipts.py',
    'tools/guest_compatibility.py', 'tools/java_guest/compiler_diagnostics.py',
    'tools/guest_compatibility_context.py', 'tools/guest_compatibility_outcomes.py',
    'tools/dev_workflow/node_diagnostics.py',
    '.github/workflows/compiler-compatibility.yml',
    *(fixture.SOURCE+language+'/'+name for language, names in (
        ('java', ('Core.java', 'Library.java', 'Capsule.java')),
        ('dotnet', ('Core.cs', 'Library.cs', 'Main.cs'))) for name in names)))))


def java_counterfactual(app, output, native, wasi_sdk, cache, deadline, positive):
    source = app/'src/dev/latent/app/Capsule.java'; original = read_file(source)
    closure = inputs.verify_inputs(app, 'java'); before = snapshot(app)
    record = fixture.counterfactual_java(app)
    destination = output/'counterfactual-build'
    try:
        changed = snapshot(app)
        require(set(changed) == set(before) and [name for name in before if changed[name] != before[name]]
            == ['src/dev/latent/app/Capsule.java'], 'compiler-diagnostics-counterfactual-one-source-path-only')
        try:
            java_build(app, destination, native['capsule_contracts'], native['package'], REPOSITORY,
                wasi_sdk, read_only_cache=cache, runtime_profile=FIBER_IO_PROFILE,
                timeout=min(900, deadline-time.monotonic()-5), compiler_methods=True, _deadline=deadline)
        except Exception as error:
            record['originalFailureCategory'] = type(error).__name__
        else:
            raise RuntimeError('compiler-diagnostics-reachable-native-unexpectedly-compiled')
        failure = read_json(destination/'BUILD-FAILED.json')
        require(read_file(destination/'source-inputs.json', 32*1024**2) == inventory(changed),
            'compiler-diagnostics-counterfactual-exact-normal-source-capture')
        require(failure['stage'] == 'compile' and len([row for row in failure['commands']
            if row['stage'] == 'java-to-c' and type(row.get('exitCode')) is int and row['exitCode'] != 0]) == 1,
            'compiler-diagnostics-counterfactual-real-teavm-refusal')
        require(read_json(destination/'java-classpath.json') == read_json(output/'build/java-classpath.json')
            and read_file(destination/'compiler-inputs.json', 32*1024**2)
                == read_file(output/'build/compiler-inputs.json', 32*1024**2)
            and inputs.verify_inputs(app, 'java').identity == closure.identity,
            'compiler-diagnostics-counterfactual-same-libraries-and-compiler')
        report = read_json(destination/'compatibility-java-compiler-report.json', 65536)
        compatibility.validate(report)
        data = positive['originalJars'][fixture.JAVA_IDS[1]]['digest']
        matches = [row for row in report['findings'] if row.get('classification') == 'target-incompatible'
            and row.get('phase') == 'compile' and row.get('evidence') == 'compiler'
            and row.get('symbol') == 'outside.diagnosticsdata.Core.opaqueNative'
            and row.get('packageDigest') == data]
        require(len(matches) == 1 and report['componentDigest'] is None
            and report['sourceDigest'] == digest(read_file(destination/'source-inputs.json', 32*1024**2)),
            'compiler-diagnostics-exact-native-refusal-bound-to-original-jar')
        record.update(compilerFailureObserved=True, exactCompilerFinding=matches[0],
            libraryOriginalDigest=data, compilerReport=file_identity(destination/'compatibility-java-compiler-report.json', 65536),
            eliminatedScope='one-exact-declaration-with-unselected-root-edge',
            arbitraryNativeApiSupport='unknown', applicationInitializerExecutedOnHost=False)
        write_json(output/'counterfactual.json', record); return record
    finally:
        source.write_bytes(original)
        require(snapshot(app) == before and inputs.verify_inputs(app, 'java').identity == closure.identity,
            'compiler-diagnostics-counterfactual-original-inputs-restored')


def execution_report(language, observed, capture, node, counterfactual=None):
    """Attach only this reviewed fixture's actual assertions, never guess from a graph.

Caught fallback is established by the exact ordinary dependency implementation
and its signed returned counters. Uncaught generic traps retain unknown cause.
The original packaged report is immutable; this is a separate finite report.
"""
    source = observed['documents']['source-inputs.json']['sha256']
    component = observed['component']['sha256']
    require(node['status'] == node['programme']['status'] == 'passed'
        and [(row['mode'], row['label']) for row in node['programme']['cases']] == list(
            (('init', 'init'), ('callback', 'callback'), ('init-trap', 'init-trap'),
             ('fresh', 'after-init-trap'), ('callback-trap', 'callback-trap'), ('fresh', 'after-callback-trap'))),
        'compiler-diagnostics-complete-finite-runtime-before-attribution')
    from tools.compiler_compatibility_node import invocation
    for row in node['programme']['cases']:
        raw = row['invocation']
        invocation(raw, raw['response']['data']['resolvedRevision'], component, language, row['mode'])
    package = capture['originalJars'][fixture.JAVA_IDS[1]]['digest'] if language == 'java' \
        else capture['originalPackages'][fixture.DOTNET_IDS[1]]['package']
    operation = 'java.io.FileInputStream' if language == 'java' else 'System.IO.File.OpenRead'
    findings = [compatibility.finding('unsupported-reached', phase, 'actual-component', operation=operation,
        package_digest=package, source_digest=source, owner_issue=741 if language == 'java' else 746)
        for phase in ('initialization', 'invocation')]
    findings.extend(compatibility.finding('unresolved-behavior', phase, 'actual-component', operation=label,
        package_digest=package, source_digest=source) for phase, label in
        (('initialization', 'uncaught-initializer-cause-unknown'), ('invocation', 'uncaught-callback-cause-unknown')))
    if language == 'java':
        query = observed.get('compilerQueries', {})
        exact = [row for row in query.get('methods', [])
            if row.get('packageDigest') == package and row.get('symbol') == 'outside.diagnosticsdata.Core.opaqueNative']
        require(counterfactual is not None and counterfactual['compilerFailureObserved'] is True
            and counterfactual['onlyRootEdgeAdded'] is True and counterfactual['libraryBytesChanged'] is False
            and counterfactual['libraryOriginalDigest'] == package and len(exact) == 1
            and exact[0].get('declaration') == 'native' and exact[0].get('state') == 'not-retained'
            and exact[0].get('apiClassification') == 'unknown'
            and query.get('scope') == 'completed-dependency-map-exact-method-only',
            'compiler-diagnostics-concrete-counterfactual-before-eliminated-api-attribution')
        findings.append(compatibility.finding('unsupported-eliminated', 'compile', 'compiler',
            operation='outside.diagnosticsdata.Core.opaqueNative', package_digest=package, source_digest=source))
    else:
        findings.append(compatibility.finding('unresolved-behavior', 'compile', 'compiler',
            operation='OutsideDiagnosticsData.Core.DeadUnsupported', package_digest=package, source_digest=source))
    findings.append(compatibility.finding('lifecycle-unproven', 'retirement', 'not-evaluated',
        operation='arbitrary-library-worker-drain'))
    return compatibility.report(language, source, component,
        FIBER_IO_PROFILE if language == 'java' else 'runtime-managed',
        [{'kind': 'application', 'digest': source}, {'kind': 'compiler',
            'digest': observed['documents']['compiler-inputs.json']['sha256']},
         {'kind': 'runtime', 'digest': observed['documents']['runtime-profile.json']['sha256']}], findings)


def qualify(language, native_directory, tool_directory, output, *, read_only_cache=None):
    require(language in {'java', 'dotnet'} and sys.platform == 'linux' and sys.version_info >= (3, 13),
        'compiler-diagnostics-linux-python313-and-selected-language')
    native_directory, tool_directory = (Path(value).resolve(strict=True) for value in (native_directory, tool_directory))
    output = Path(output).absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents
        and all(output != path and output not in path.parents and path not in output.parents
            for path in (native_directory, tool_directory)), 'compiler-diagnostics-separated-owned-output')
    native_scope = assert_current(); compiled = products.verify_prepared(native_directory)
    native = products.native_products(native_directory)
    for path in native.values(): path.chmod(0o700)
    native_before = {name: file_identity(path, 512*1024**2) for name, path in native.items()}
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=10).decode().strip()
    materials = {name: file_identity(ROOT/name, 32*1024**2) for name in MATERIALS}
    output = fresh(output)
    commands = Commands(ROOT, fresh(output/'commands'), build_environment(output), deadline_seconds=1800, command_seconds=120)
    record = {'schemaVersion': 'latent.compiler-diagnostics.qualification.v1', 'language': language,
        'status': 'incomplete', 'source': source, 'materials': materials, 'nativeSource': native_scope,
        'compiledNative': compiled, 'nativeProducts': native_before, 'nativeProductsBuilt': 0,
        'guestComponentsCompiled': 0, 'applicationCodeExecutedOnCompilerHost': False,
        'fullTicketQualification': False, 'arbitraryApiSupport': 'unknown', 'workerDrainQualified': False}
    stage = 'outside-library-normal-reviewed-capture'
    try:
        app = fixture.project(language, output/'project')
        if language == 'java':
            capture = fixture.java_capture(app, output/'outside', commands)
            cache_output = fresh(output/'compiler-cache')
            cache = compiler_cache(commands, tool_directory, cache_output, read_only_cache)
            record['compilerCacheSelection'] = read_json(cache_output/'compiler-cache-selection.json')
            record['unsignedNormalCompilerAcquisitionControls'] = int(read_only_cache is None)
        else:
            expected_runtime = runtime_inputs(ROOT)
            require(read_file(tool_directory/'runtime-inputs.json') == expected_runtime,
                'compiler-diagnostics-current-prepared-managed-adapters')
            record['compilerInstallation'] = {name: file_identity(tool_directory/name, 16*1024**2) for name in
                ('INSTALL-COMPLETE.json', 'runtime-inputs.json', 'wasi-sdk.json')}
            capture = fixture.dotnet_capture(app, output/'outside', tool_directory, deadline=commands.deadline)
        record['capture'] = capture; write_json(output/'capture.json', capture)
        files = snapshot(app)
        stage = 'one-fresh-substantive-compiler-observed-component'
        if language == 'java':
            artifact = java_build(app, output/'build', native['capsule_contracts'], native['package'], REPOSITORY,
                tool_directory, read_only_cache=cache, runtime_profile=FIBER_IO_PROFILE,
                timeout=min(900, commands.deadline-time.monotonic()-600), compiler_methods=True)
        else:
            artifact = dotnet_build(app, output/'build', native['capsule_contracts'], native['package'],
                REPOSITORY, tools=tool_directory, offline=True, compiler_methods=True)
        record['guestComponentsCompiled'] = 1
        record['build'] = build_evidence(artifact, language, files, capture)
        if language == 'java':
            stage = 'same-libraries-one-edge-concrete-compiler-refusal'
            record['counterfactual'] = java_counterfactual(app, output, native, tool_directory, cache, commands.deadline, capture)
        stage = 'signed-six-constructor-initializer-and-callback-results'
        record['node'] = execute(artifact, native, output/'node', commands.deadline, language, record['build'])
        write_json(output/'compatibility-execution-report.json', execution_report(language, record['build'], capture,
            record['node'], record.get('counterfactual')))
        record['compatibilityExecutionReport'] = file_identity(output/'compatibility-execution-report.json', 65536)
        require(build_evidence(artifact, language, files, capture) == record['build']
            and snapshot(app) == files and inputs.verify_inputs(app, language).identity == capture['capturedInputIdentity']
            and products.verify_prepared(native_directory) == compiled and assert_current() == native_scope
            and native_before == {name: file_identity(path, 512*1024**2) for name, path in native.items()}
            and materials == {name: file_identity(ROOT/name, 32*1024**2) for name in MATERIALS}
            and subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=10).decode().strip() == source
            and time.monotonic() < commands.deadline, 'compiler-diagnostics-final-source-products-and-package-currentness')
        if language == 'dotnet':
            require(runtime_inputs(ROOT) == expected_runtime and record['compilerInstallation'] == {
                name: file_identity(tool_directory/name, 16*1024**2) for name in record['compilerInstallation']},
                'compiler-diagnostics-final-managed-compiler-inputs-unchanged')
        record.update(status='passed', commands=commands.records, signedOutcomes=6, preEntryDenials=1)
        write_workflow_receipt(output/'qualified.json', record); return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__, commands=commands.records)
        write_workflow_receipt(output/'FAILED.json', record); raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--language', choices=('java', 'dotnet'), required=True)
    for name in ('native', 'tools', 'output'): parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--read-only-cache', type=Path)
    args = parser.parse_args()
    print(qualify(args.language, args.native, args.tools, args.output, read_only_cache=args.read_only_cache)['status'])
