"""Source-bound compiler observations for this finite application programme.

This reader does not infer runtime support, execution or arbitrary API absence
from method metadata. Runtime results are attached by the separate controller.
"""
from __future__ import annotations

from tools import compiler_compatibility_fixture as fixture
from tools import guest_runtime_receipts, guest_compatibility, guest_compatibility_context
from tools.build_snapshot import canonical
from tools.dev_workflow.common import encode
from tools.java_capsule_build import FIBER_IO_PROFILE
from tools.java_guest import coroutine_patch
from tools.dotnet_guest import closed_filesystem, managed_work, retirement, task_wait
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_sdk_scratch import package_identity
from tools.rust_capsule_project import digest, inventory, read_file, read_json

PARAMETERS = {
    'java': {'compiler': 'teavm-c', 'entryPoint': 'dev.latent.app.Capsule', 'target': 'wasm32-wasip1',
        'bindings': 'lsf-java-wit-v1', 'optimization': 'O2', 'javaHeapBytes': 4194304},
    'dotnet': {'compiler': 'native-aot-llvm', 'bindings': 'wit-bindgen-csharp', 'language': 'csharp',
        'target': 'wasi-wasm', 'runtime': 'native-aot', 'locked': True, 'ambientWasi': False},
}


def material(observed, name, path, maximum=32*1024**2):
    identity = file_identity(path, maximum)
    require([row for row in observed['materials'] if row['name'] == name] == [
        {'name': name, 'digest': identity['sha256'], 'size': identity['bytes']}],
        'compiler-diagnostics-exact-observed-'+name)
    return identity


def java_queries(value, classpath, capture):
    artifacts = {row['id']: row for row in classpath['artifacts']}
    require(set(artifacts) == set(fixture.JAVA_IDS)
        and all(artifacts[name]['originalDigest'] == identity['digest']
            for name, identity in capture['originalJars'].items()),
        'compiler-diagnostics-exact-original-jar-closure')
    selected = {row['id']: row for row in value['methods']}
    witnesses = []
    methods = (
        (fixture.JAVA_IDS[1], 'outside.diagnosticsdata.Core', '<clinit>()V', 'linked'),
        (fixture.JAVA_IDS[1], 'outside.diagnosticsdata.Core', '<init>()V', 'linked'),
        (fixture.JAVA_IDS[1], 'outside.diagnosticsdata.Core', 'fallback()I', 'linked'),
        (fixture.JAVA_IDS[1], 'outside.diagnosticsdata.Core', 'uncaught()V', 'linked'),
        (fixture.JAVA_IDS[1], 'outside.diagnosticsdata.Core', 'opaqueNative()I', 'not-retained'),
        (fixture.JAVA_IDS[0], 'outside.diagnostics.Library', '<init>()V', 'linked'),
        (fixture.JAVA_IDS[0], 'outside.diagnostics.Library', 'run(Ljava/lang/String;)Ljava/lang/String;', 'linked'),
        (fixture.JAVA_IDS[0], 'outside.diagnostics.Library$1', 'run()V', 'linked'),
    )
    for package, owner, method, state in methods:
        entries = [row for row in artifacts[package]['entries'] if row['path'] == owner.replace('.', '/')+'.class']
        require(len(entries) == 1, 'compiler-diagnostics-exact-method-class')
        identity = digest(encode({'classDigest': entries[0]['digest'], 'owner': owner, 'method': method}))[7:]
        row = selected.get(identity)
        require(row is not None and row['classDigest'] == entries[0]['digest']
            and row['packageDigest'] == artifacts[package]['originalDigest'] and row['state'] == state
            and row['apiClassification'] == 'unknown', 'compiler-diagnostics-completed-exact-java-query')
        witnesses.append(row)
    return {'methods': witnesses, 'scope': 'completed-dependency-map-exact-method-only',
        'nativeApiSupport': 'unknown-until-exact-counterfactual-compiler-refusal'}


def dotnet_queries(value, capture):
    assemblies = {row['assembly'] for row in capture['originalPackages'].values()}
    require(all(row['assemblyDigest'] in assemblies for row in value['methods']
        if row['symbol'].startswith(('OutsideDiagnostics.', 'OutsideDiagnosticsData.'))),
        'compiler-diagnostics-original-captured-managed-assemblies')
    witnesses = []
    states = {
        'OutsideDiagnosticsData.Core..cctor': 'linked',
        'OutsideDiagnosticsData.Core..ctor': 'linked',
        'OutsideDiagnosticsData.Core.Fallback': 'linked',
        'OutsideDiagnosticsData.Core.Uncaught': 'linked',
        'OutsideDiagnosticsData.Core.DeadUnsupported': 'not-retained',
        'OutsideDiagnostics.Library..ctor': 'linked',
        'OutsideDiagnostics.Library.Run': 'linked',
        'OutsideDiagnostics.Library.Callback': 'linked',
        'OutsideDiagnostics.Library.FailingCallback': 'linked',
    }
    for symbol, state in states.items():
        rows = [row for row in value['methods'] if row['symbol'] == symbol]
        require(len(rows) == 1 and rows[0]['assemblyDigest'] in assemblies
            and rows[0]['state'] == state and rows[0]['apiClassification'] == 'unknown',
            'compiler-diagnostics-completed-exact-dotnet-query')
        witnesses.append(rows[0])
    return {'methods': witnesses, 'mappingAnchorCount': value['mappingAnchorCount'],
        'scope': 'complete-bounded-IL-scanner-exact-nongeneric-method-only',
        'deadWrapperApiSupport': 'unknown'}


def managed_profile(artifact, observed, profile):
    task = read_json(artifact/'task-wait-port.json'); fs = read_json(artifact/'closed-filesystem-port.json')
    owner = read_json(artifact/'retirement-port.json'); io = read_json(artifact/'internal-io-port.json')
    coverage = read_json(artifact/'closed-runtime-coverage.json')
    for name, filename in (('dotnet-task-wait-port', 'task-wait-port.json'),
        ('dotnet-closed-filesystem-port', 'closed-filesystem-port.json'),
        ('dotnet-internal-io-port', 'internal-io-port.json'),
        ('closed-runtime-coverage', 'closed-runtime-coverage.json')):
        material(observed, name, artifact/filename)
    require(profile['profile'] == 'runtime-managed' and 'closedIoPort' not in profile
        and profile['retirementPort'] == owner and owner['profile'] == retirement.PROFILE
        and owner['privateImport'] == retirement.IDENTITY and owner['publicGraphUnchanged'] is True
        and owner['authority'] == 'none' and owner['managedWork'] == {'profile': managed_work.PROFILE,
            'privateImport': managed_work.IDENTITY, 'authority': 'none', 'qualified': False}
        and profile['internalIoPort'] == io and io['profile'] == 'dotnet-private-async-io-v1'
        and io['coreBytesUnchanged'] is True and io['publicApplicationGraphUnchanged'] is True
        and profile['adapter']['name'] == 'managed-activation-runtime'
        and [row for row in observed['materials'] if row['name'] == profile['adapter']['name']] == [profile['adapter']]
        and coverage['gaps'] == [] and coverage['authority'] == 'none'
        and coverage['compilerPrivateImports'] == [retirement.IDENTITY, managed_work.IDENTITY]
        and coverage['rawComponentDigest'] == io['selectedDigest']
        and coverage['runtimeAdapterDigest'] == profile['adapter']['digest']
        and task['profile'] == task_wait.PROFILE and task['completion'] == 'actual-task-only'
        and task['managedAcceptedWork']['patch'] == 'latent.dotnet.managed-accepted-work.v2'
        and task['managedAcceptedWork']['authoritativeLimits'] == 'original-activation-owner-ledger'
        and task['managedAcceptedWork']['newAssemblyReferences'] == 0
        and len(task['nativeAotReferenceBinding']['responseFiles']) == 1
        and task['nativeAotReferenceBinding']['finalCoreLibDerivation']['selectedDigest'] == fs['derived']['digest']
        and fs['profile'] == closed_filesystem.PROFILE and fs['filesystemAuthority'] is False
        and fs['publicWrappersUnchanged'] is True and fs['modifiedOriginalMethods'] == 2
        and fs['nativeAotReferenceBinding']['selectedCoreLibDigest'] == fs['derived']['digest'],
        'compiler-diagnostics-current-managed-task-and-closed-filesystem-binding')
    return {name: file_identity(artifact/name, 32*1024**2) for name in
        ('task-wait-port.json', 'closed-filesystem-port.json', 'retirement-port.json',
         'internal-io-port.json', 'closed-runtime-coverage.json')}


def build_evidence(artifact, language, files, capture):
    require(language in PARAMETERS, 'compiler-diagnostics-closed-language')
    identities = {name: file_identity(artifact/name, 32*1024**2) for name in
        ('BUILD-COMPLETE.json', 'build-observation.json', 'source-inputs.json', 'recipe-inputs.json',
         'compiler-inputs.json', 'package-inputs.json', 'runtime-profile.json', 'application-dependencies.json',
         'compiler-method-observation-selection.json', 'compatibility-compiler-methods.json',
         'compatibility-report.json', 'compatibility-context.json')}
    component = file_identity(artifact/'component.wasm', 64*1024**2)
    marker, observed, profile = (read_json(artifact/name, 32*1024**2) for name in
        ('BUILD-COMPLETE.json', 'build-observation.json', 'runtime-profile.json'))
    require(marker['packageAssembled'] is True and marker['componentDigest'] == observed['componentDigest'] == component['sha256']
        and observed['componentSize'] == component['bytes']
        and marker['observationDigest'] == identities['build-observation.json']['sha256']
        and marker['sourceDigest'] == identities['source-inputs.json']['sha256']
        and read_file(artifact/'source-inputs.json', 32*1024**2) == inventory(files)
        and observed['parameters'] == PARAMETERS[language]
        and {row['contract'] for row in read_json(artifact/'capsule.json')['imports']}
            == set(fixture.DECLARATIONS[language]),
        'compiler-diagnostics-exact-normal-build-and-closed-parameters')
    for name, filename in (('build-recipe', 'recipe-inputs.json'), ('package-inputs', 'package-inputs.json'),
        ('source-snapshot', 'source-inputs.json'), ('compiler-method-reachability', 'compatibility-compiler-methods.json'),
        ('compiler-method-observation-selection', 'compiler-method-observation-selection.json')):
        material(observed, name, artifact/filename)
    require(read_json(artifact/'compiler-method-observation-selection.json') == {
        'schemaVersion': 'lsf.guest.compiler-method-selection.v1', 'language': language, 'selected': True,
        'status': 'observed', 'observation': {'name': 'compiler-method-reachability',
            'digest': identities['compatibility-compiler-methods.json']['sha256'],
            'size': identities['compatibility-compiler-methods.json']['bytes']}},
        'compiler-diagnostics-selected-observed-material-not-recipe-option')
    graph = guest_runtime_receipts.captured_graph(files)
    report = guest_compatibility.read(read_file(artifact/'compatibility-report.json', 65536))
    guest_compatibility_context.read(read_file(artifact/'compatibility-context.json', 65536), report=report,
        source=identities['source-inputs.json']['sha256'], component=component['sha256'])
    bindings = {'source': identities['source-inputs.json']['sha256'], 'component': component['sha256'],
        'compiler': identities['compiler-inputs.json']['sha256'], 'recipe': identities['recipe-inputs.json']['sha256'],
        'graph': digest(canonical(graph)) if graph is not None else None}
    methods = read_json(artifact/'compatibility-compiler-methods.json', 65536)
    if language == 'java':
        from tools.java_guest import reachability
        reachability.validate(methods, **bindings)
        material(observed, 'compiler-closure', artifact/'compiler-inputs.json')
        material(observed, 'java-runtime-profile', artifact/'runtime-profile.json')
        material(observed, 'java-classpath-selection', artifact/'java-classpath.json')
        require(marker['javaRuntimeProfile'] == profile['profile'] == FIBER_IO_PROFILE
            and {'dev.latent.app.Capsule', 'outside.diagnostics.Library', 'outside.diagnosticsdata.Core'}
                <= set(profile['checkpointClasses']), 'compiler-diagnostics-original-fiber-library-selection')
        prepared = read_json(artifact/'coroutine-compiler-preparation.json')
        require(prepared['schemaVersion'] == 'latent.java.coroutine-compiler-patch.v1'
            and prepared['upstreamSourceSha256'] == coroutine_patch.UPSTREAM_SHA256
            and prepared['originalInputsUnchanged'] is True and prepared['realCorrectedIrInputsPreserved'] is True
            and prepared['realOriginalIrDefectObserved'] is True
            and set(prepared['replacedClasses']) == coroutine_patch.PATCH_CLASSES,
            'compiler-diagnostics-exact-reviewed-coroutine-derivation')
        query = java_queries(methods, read_json(artifact/'java-classpath.json'), capture)
        identities.update({name: file_identity(artifact/name, 32*1024**2) for name in
            ('java-classpath.json', 'coroutine-compiler-preparation.json', 'source-origins.json')})
    else:
        from tools.dotnet_guest import reachability
        reachability.validate(methods, **bindings)
        material(observed, 'compiler-inputs', artifact/'compiler-inputs.json')
        material(observed, 'runtime-profile', artifact/'runtime-profile.json')
        require(set(profile['declaredImports']) == set(fixture.DECLARATIONS[language]),
            'compiler-diagnostics-exact-managed-declarations')
        identities.update(managed_profile(artifact, observed, profile))
        query = dotnet_queries(methods, capture)
    return {'component': component, 'documents': identities, 'compilerQueries': query,
        'package': package_identity(artifact, marker), 'sourceOfApiSupport': 'runtime-results-only',
        'compilerObservationIsExecutionEvidence': False}
