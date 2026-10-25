"""Fail-closed rollup of the fixed hosted owners; never an admission authority.

Artifact/run authentication and raw-channel review remain required separately.
Historical evidence retains its original source/profile; no old guest is
relabeled as running with the new native bundle. This file runs no application.
"""
from pathlib import Path
import json
import os
import sys
import time

if __package__ in {None, ''}: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import compatibility_closure_node as node
from tools import compatibility_native_products as native
from tools import guest_api_analysis as api
from tools.dev_workflow.common import digest, require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, fresh, read_file, read_json, write_json

LANGUAGES = ('c', 'rust', 'go', 'java', 'dotnet', 'typescript')
CELLS = (*LANGUAGES, 'go-queues', 'typescript-initializer')
PRESERVED_CELLS = ('java', 'typescript', 'go-queues')
PRESERVED_SOURCE = 'cc8b88b18abda6e03fc3097d8af658f5e16022f6'
MAX_PUBLIC_BYTES = 256 * 1024**2
MAX_PUBLIC_FILES = 8192
MAX_PUBLIC_FILE = 64 * 1024**2
PUBLIC_METADATA_RESERVE = 4 * 1024**2
HISTORY = {
    'sdk-explicit-fallback-2026-10-22.json': {'bytes': 16191, 'sha256': 'sha256:8b704da1a03cafd0d4130111fbec27dd24361360095a7153ef6e6d9664e3a44f'},
    'rust-compatibility-signed-2026-10-21.json': {'bytes': 41993, 'sha256': 'sha256:15fdd75fbb68b1ac7bb12e3ed3fee15b3667344bd0dc5b84b7791c78a837ed71'},
    'java-compiler-observations-signed-2026-10-21.json': {'bytes': 78822, 'sha256': 'sha256:06e161401174108347b02f3e35f6fe55012a5303c22e5bb08168dbda0d3e6a80'},
    'dotnet-compiler-observations-signed-2026-10-21.json': {'bytes': 77766, 'sha256': 'sha256:1bb4e5894fd2f477dc33780dced78f803ab055c77c7af100eaecf5a4dd865abe'},
    'typescript-explicit-fallback-2026-10-22.json': {'bytes': 37726, 'sha256': 'sha256:38ab7cbbbc56f5a449e46f2ea0a87e51d9d8a49801dd5a2a93f5c06bab5cf83a'},
    'typescript-elimination-2026-10-22.json': {'bytes': 9266, 'sha256': 'sha256:a39011fcafbf94fa3476fd079f79dc28010aaafb00da3d1232c9640d2c88e860'},
    'six-language-final-import-controls-2026-10-21.json': {'bytes': 37035, 'sha256': 'sha256:bb64964a9afa4cdbc5a80000b42dc462ed32e03195cec0c4b9bc529c90ed1a1c'}}


def historical(root=ROOT):
    values = {}
    for name, identity in HISTORY.items():
        path = Path(root) / 'docs/testing/evidence' / name
        require(file_identity(path, 1024**2) == identity, 'compatibility-matrix-original-history-bytes')
        values[name] = json.loads(read_file(path, 1024**2))
    imports = values['six-language-final-import-controls-2026-10-21.json']
    require(imports['status'] == 'passed' and imports['scope'] == 'final-component-inspector-only'
        and imports['guestInvocations'] == 0 and imports['runtimeQualification'] is False
        and {row['language'] for row in imports['cases']} == set(LANGUAGES),
        'compatibility-matrix-original-six-import-inspector-scope')
    require(values['sdk-explicit-fallback-2026-10-22.json']['status'] == 'passed'
        and set(values['sdk-explicit-fallback-2026-10-22.json']['languages']) == {'c', 'go'}
        and values['rust-compatibility-signed-2026-10-21.json']['status'] == 'passed'
        and values['rust-compatibility-signed-2026-10-21.json']['qualification']['initializationFailure'] == 'not-tested'
        and values['typescript-explicit-fallback-2026-10-22.json']['verification']['status'] == 'passed',
        'compatibility-matrix-original-fallback-history-without-initializer-credit')
    for language in ('java', 'dotnet'):
        value = values[language + '-compiler-observations-signed-2026-10-21.json']
        require(value['status'] == 'qualified-finite-programme' and len(value['signedCases']) == 6
            and value['verification']['status'] == 'passed', 'compatibility-matrix-original-managed-initializer-history')
    return [{'path': 'docs/testing/evidence/' + name, **identity,
        'scope': 'original-historical-source-profile-only', 'currentNativeExecutionClaimed': False}
        for name, identity in HISTORY.items()]


def signed(value, component, expected_count, *, expected=None, kind='api-pair', queue_ceiling=None):
    require(value['status'] == value['programme']['status'] == 'passed'
        and value['component']['sha256'] == component
        and value['nodeShutdown']['reaped'] is True and value['nodeShutdown']['record']['clean'] is True
        and len(value['programme']['cases']) == expected_count, 'compatibility-matrix-complete-original-node-owner')
    cases = ([('probe', 'probe'), ('probe', 'fresh-after-probe')] if kind == 'api-pair' else
        [('task-limit', 'task-limit'), ('fresh', 'fresh-after-task'), ('timer-limit', 'timer-limit'), ('fresh', 'fresh-after-timer')]
        if kind == 'typescript-resources' else [('fresh', 'queue-8')]
        if queue_ceiling == 8 else [('fresh', 'fresh-before-queue'), ('parallel', 'queue-9'), ('fresh', 'fresh-after-queue')])
    require(value['programme']['kind'] == kind and
        [(row['mode'], row['label']) for row in value['programme']['cases']] == cases,
        'compatibility-matrix-exact-original-case-order')
    for row in value['programme']['cases']:
        invocation = row['invocation']
        original = node.original_invocation(invocation, invocation['response']['data']['resolvedRevision'],
            component, value['targetBudget'])
        require(original == row['originalDiagnostic'], 'compatibility-matrix-original-terminal-not-rewritten')
        fact = row['operationObservation']
        refusal = row['mode'] if kind == 'typescript-resources' and row['mode'] in node.RESOURCE_EXPECTED else \
            row['label'] if kind == 'go-queues' and row['label'] in node.RESOURCE_EXPECTED else None
        if refusal is not None:
            from tools import guest_compatibility_outcomes as outcomes
            reason, dimension, bound, requested = node.RESOURCE_EXPECTED[refusal]
            require(type(fact) is dict and invocation['exitCode'] == 4
                and invocation['response']['category'] == 'platform-failure'
                and invocation['response']['error']['code'] in {'guest-trap', 'guest-runtime-error'},
                'compatibility-matrix-original-known-resource-refusal')
            observed = outcomes.validate_node_observation(fact['operationFact'])
            require(observed['state'] == 'observed' and observed['scope'] == 'activation-id-service-only'
                and observed['implementationBinding'] == 'unavailable'
                and observed['resourceDimension'] == dimension
                and observed['fields']['reason'] == str(reason)
                and observed['fields']['configured_bound'] == str(bound)
                and observed['fields']['calculated_requirement'] == str(requested),
                'compatibility-matrix-exact-original-operation-bound')
            require(fact['terminalCause'] == original['cause'] and fact['implementationBinding'] == 'unavailable'
                and fact['apiAttributionFromManagementFact'] is False,
                'compatibility-matrix-operation-not-terminal-or-implementation-proof')
        else:
            if kind == 'go-queues':
                from tools.go_resource_runtime_fixture import EXPECTED
                answer = [{'ok': EXPECTED[row['mode']]}]
            else:
                answer = ['compatibility-resource|fresh=1'] if kind == 'typescript-resources' else expected
            require(fact is None and type(answer) is list and invocation['exitCode'] == 0
                and invocation['decoded'] == answer, 'compatibility-matrix-exact-original-success-and-fresh')
    return {'cases': expected_count, 'componentDigest': component, 'originalTerminalPreserved': True}


def assemble(records, *, source_commit, root=ROOT, preserved_directory=None, diagnostic_output=None):
    require((preserved_directory is None) == (diagnostic_output is None),
        'compatibility-matrix-preservation-with-current-diagnostics')
    required = set(CELLS) - set(PRESERVED_CELLS) if preserved_directory is not None else set(CELLS)
    require(type(records) is dict and set(records) == required, 'compatibility-matrix-missing-or-extra-required-cells')
    require(type(source_commit) is str and len(source_commit) == 40
        and all(c in '0123456789abcdef' for c in source_commit), 'compatibility-matrix-feature-source')
    preservation, diagnostics = {}, {}
    if preserved_directory is not None:
        from tools import compatibility_preserved_cells as retained
        from tools.compatibility_preserved_diagnostics import diagnose
        verified = retained.verify_prepared(Path(preserved_directory))
        require(set(verified['records']) == set(PRESERVED_CELLS),
            'compatibility-matrix-exact-three-original-executions')
        records = {**records, **verified['records']}
        preservation = verified['sourceEquivalence']
        diagnostic_output = fresh(Path(diagnostic_output))
        for cell in PRESERVED_CELLS:
            diagnostics[cell] = diagnose(Path(preserved_directory) / cell /
                ('build' if cell == 'java' else 'baseline'), diagnostic_output / cell,
                cell=cell, source_commit=source_commit)
    rows = []
    for cell in CELLS:
        value = records[cell]; language = 'go' if cell == 'go-queues' else 'typescript' if cell == 'typescript-initializer' else cell
        runtime_source = PRESERVED_SOURCE if cell in diagnostics else source_commit
        require(value['status'] == 'passed' and value['sourceCommit'] == runtime_source
            and value['language'] == language and value['cell'] == cell and value['nativeBuildCount'] == 0
            and value['native']['compiledSource'] == native.QUALIFIED['source']
            and value['native']['producerRun'] == native.QUALIFIED['run']
            and value['native']['producerJob'] == native.QUALIFIED['job'], 'compatibility-matrix-detached-or-incomplete-owner')
        baseline = value['baseline']
        analysis = api.validate(diagnostics[cell]['currentAPI'] if cell in diagnostics else baseline['api'])
        require(analysis['state'] == 'observed' and analysis['language'] == language
            and analysis['componentDigest'] == baseline['component']['sha256']
            and value['defaultPresentation']['explicitAnalysisSelector'] is False,
            'compatibility-matrix-ordinary-default-source-bound-analysis')
        if cell in {'c', 'rust', 'go', 'dotnet'}:
            pair = value['compilerPair']
            require(pair['libraryInputsUnchanged'] is True and pair['authority'] == 'none'
                and pair['runtimeExecution'] == 'not-observed'
                and pair['scope'] == ('one-controlled-api-callee-retention-differential' if cell == 'dotnet'
                    else 'one-controlled-compiler-call-edge'), 'compatibility-matrix-exact-compiler-differential-scope')
            signed(value['baselineSigned'], baseline['component']['sha256'], 2,
                expected=[{'ok': 'api|answer=42|fresh=1' if cell == 'dotnet' else 'api|' + cell + '|edge-not-taken'}])
            signed(value['reachedSigned'], value['reached']['component']['sha256'], 2,
                expected=[{'ok': 'api|answer=42|fresh=1' if cell == 'dotnet' else 'api|' + cell + '|unsupported'}])
        if cell in {'c', 'rust', 'go'}:
            scope = value['initializationScope']
            require(scope['scope'] == 'reached-unsupported-during-initialization/fallback'
                and scope['initializerFailureClaimed'] is False and scope['componentStartClaimed'] is False
                and scope['repeatInFreshStore'] is True
                and scope['kind'] == {'c': 'eager-c-constructor', 'go': 'eager-package-variable',
                    'rust': 'lazy-static-during-invocation'}[cell], 'compatibility-matrix-actual-initialization-scope')
            initialized = value['initializerSigned']; signed(initialized, value['initializer']['component']['sha256'], 2,
                expected=[{'ok': 'api|' + cell + '|initialization|unsupported|result=42|count=1'}])
            require(all(row['invocation']['decoded'] == [{'ok': 'api|' + cell
                + '|initialization|unsupported|result=42|count=1'}] for row in initialized['programme']['cases']),
                'compatibility-matrix-native-Unsupported-initializer-count-and-fresh')
        elif cell == 'java':
            from tools.compiler_compatibility_node import CASES, invocation
            observed = value['signed']
            require(observed['status'] == observed['programme']['status'] == 'passed'
                and observed['nodeShutdown']['reaped'] is True and observed['nodeShutdown']['record']['clean'] is True
                and value['compilerPair']['compilerFailureObserved'] is True
                and value['compilerPair']['onlyRootEdgeAdded'] is True
                and value['compilerPair']['libraryBytesChanged'] is False
                and [(row['mode'], row['label']) for row in observed['programme']['cases']] == list(CASES),
                'compatibility-matrix-original-Java-compiler-and-six-outcomes')
            for row in observed['programme']['cases']:
                raw = row['invocation']
                invocation(raw, raw['response']['data']['resolvedRevision'],
                    baseline['component']['sha256'], 'java', row['mode'])
        elif cell == 'typescript':
            signed(value['signed'], baseline['component']['sha256'], 4, kind='typescript-resources')
            facts = [row['operationObservation'] for row in value['signed']['programme']['cases']
                     if row['operationObservation'] is not None]
            require([fact['observedOperationResource'] for fact in facts] == ['tasks', 'timers'],
                'compatibility-matrix-real-task-and-timer-facts')
        elif cell == 'go-queues':
            for ceiling, count in (('8', 1), ('9', 3)):
                signed(value['signed'][ceiling], baseline['component']['sha256'], count,
                    kind='go-queues', queue_ceiling=int(ceiling))
                facts = [row['operationObservation'] for row in value['signed'][ceiling]['programme']['cases']
                         if row['operationObservation'] is not None]
                require(len(facts) == 1 and facts[0]['observedOperationResource'] == 'queues'
                    and facts[0]['operationFact']['fields']['configured_bound'] == ceiling,
                    'compatibility-matrix-original-queue-eight-nine-differential')
        elif cell == 'typescript-initializer':
            # This mandatory cell is deliberately NOT substituted by the old
            # callback/fallback receipt or by the resource profile's clock.
            require(value['initializationScope']['kind'] == 'class-static-during-invocation'
                and value['initializationScope']['componentStartClaimed'] is False,
                'compatibility-matrix-real-TypeScript-initializer-required')
            signed(value['initializerSigned'], baseline['component']['sha256'], 2,
                expected=[{'ok': 'api|typescript|initialization|unsupported|result=42|count=1'}])
            require(all(row['invocation']['decoded'] == [{'ok':
                'api|typescript|initialization|unsupported|result=42|count=1'}]
                for row in value['initializerSigned']['programme']['cases']),
                'compatibility-matrix-real-TypeScript-native-Unsupported-and-count')
        rows.append({'cell': cell, 'language': language, 'component': baseline['component'],
            'APIAnalysisIdentity': analysis['identity'], 'sourceCommit': value['sourceCommit'],
            'diagnosticSourceCommit': source_commit,
            'executionScope': 'preserved-original-cc8b-execution' if cell in diagnostics else 'current-fixed-cell-execution',
            'arbitraryApiSafety': 'unknown', 'physicalRetirementScope': 'only-actual-fixed-owner-observations'})
    return {'schemaVersion': 'latent.compatibility.closure-matrix.v1', 'status': 'required-finite-owners-passed',
        'sourceCommit': source_commit, 'cells': rows, 'historicalEvidence': historical(root),
        'preservedExecutions': preservation, 'currentPassiveDiagnostics': diagnostics,
        'nativeSource': native.QUALIFIED['source'], 'nativeRun': native.QUALIFIED['run'],
        'sharedEngineStack': {'scope': 'unsigned-normal-component-containment-only',
            'nativeProducerStage': 'compiler-diagnostic-actual-stack-component',
            'requiredOriginalTerminal': 'StackOverflow', 'typedReason': 26,
            'freshResult': 42, 'sixSignedLanguageStackCrossproductClaimed': False},
        'arbitraryLibraryEligibility': 'not-evaluated', 'runtimeImplementationTicketsClosed': False,
        'authority': 'none', 'automaticIssueClosure': False,
        'artifactOriginAndRawChannelsRequireIndependentAuthentication': True}


def retain(source, output):
    """Fixed public synthetic programme projection, never caches or signer keys.

    This is a separate always-run admission. Incomplete evidence is useful but
    cannot pass assemble(). No partial tree is uploaded when admission refuses.
    """
    source = Path(source).resolve(strict=True)
    require(source.is_dir() and not source.is_symlink(), 'compatibility-public-original-directory')
    output = Path(output).absolute()
    require(output != source and output not in source.parents and source not in output.parents,
        'compatibility-public-separated-output')
    # Only these fixed controller-owned roots are inspected. Compiler caches,
    # extracted SDKs, source workspaces and private signer directories are absent.
    builds = ('baseline', 'build', 'reached', 'initializer', 'counterfactual-build')
    nodes = ('node', 'baseline-node', 'reached-node', 'initializer-node', 'node-8', 'node-9')
    selections = [(source, False)]
    for name in builds:
        base = source / name
        selections.append((base, False))
        selections.extend((base / child, True) for child in ('package', 'compiler-logs', 'logs'))
    selections.extend((source / child, True) for child in ('commands/logs', 'capture-commands/logs'))
    for name in nodes:
        base = source / name
        selections.append((base, False))
        selections.extend((base / child, True) for child in ('controls', 'examples-controls',
            'foreign-controls', 'commands/logs', 'signed/my-greeting/package', 'signed/my-greeting/evidence'))
        selections.append((base / 'signed', False))
    rows, total, visited = {}, 0, 0
    deadline = time.monotonic() + 60
    for base, recursive in selections:
        if not base.exists(): continue
        require(base.is_dir() and not base.is_symlink(), 'compatibility-public-original-directory')
        pending = [base]
        while pending:
            require(time.monotonic() < deadline, 'compatibility-public-admission-deadline')
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    visited += 1
                    require(visited <= MAX_PUBLIC_FILES and not entry.is_symlink(), 'compatibility-public-entry-bound')
                    path = Path(entry.path)
                    if entry.is_dir(follow_symlinks=False):
                        if recursive: pending.append(path)
                        continue
                    require(entry.is_file(follow_symlinks=False), 'compatibility-public-regular-file')
                    # Direct selection is digest/observation metadata, component
                    # and WIT only. In particular signed/*.key is never selected.
                    if not recursive and path.suffix not in {'.json', '.wasm', '.wit'}: continue
                    relative = path.relative_to(source).as_posix()
                    if relative in rows: continue
                    require(len(relative.encode('utf-8')) <= 512, 'compatibility-public-path-bound')
                    identity = file_identity(path, min(MAX_PUBLIC_FILE,
                        MAX_PUBLIC_BYTES - PUBLIC_METADATA_RESERVE - total))
                    total += identity['bytes']; rows[relative] = identity
    require(rows and len(rows) <= MAX_PUBLIC_FILES, 'compatibility-public-nonempty')
    output = fresh(output)
    for relative, identity in sorted(rows.items()):
        data = read_file(source / relative, MAX_PUBLIC_FILE)
        require({'bytes': len(data), 'sha256': digest(data)} == identity,
            'compatibility-public-original-changed')
        target = output / relative; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest = {'schemaVersion': 'latent.compatibility.public-union.v1',
        'files': rows, 'payloadBytes': total, 'maximumUnionBytes': MAX_PUBLIC_BYTES,
        'privateSignerAndCompilerCacheIncluded': False, 'qualificationInferred': False}
    raw = (json.dumps(manifest, sort_keys=True, separators=(',', ':')) + '\n').encode()
    require(len(raw) <= PUBLIC_METADATA_RESERVE and total + len(raw) <= MAX_PUBLIC_BYTES,
        'compatibility-public-union-bound')
    (output / 'ADMISSION.json').write_bytes(raw)
    return manifest


def read_retained(directory):
    from tools.phase3_resource_identity import inventory
    directory = Path(directory)
    manifest = read_json(directory / 'ADMISSION.json', PUBLIC_METADATA_RESERVE)
    require(manifest['schemaVersion'] == 'latent.compatibility.public-union.v1'
        and manifest['maximumUnionBytes'] == MAX_PUBLIC_BYTES
        and manifest['privateSignerAndCompilerCacheIncluded'] is False,
        'compatibility-public-original-admission')
    actual = inventory(directory, maximum_files=MAX_PUBLIC_FILES * 2,
        maximum_bytes=MAX_PUBLIC_BYTES, deadline=time.monotonic() + 60)
    rows = {row['path']: {key: row[key] for key in ('bytes', 'sha256')}
        for row in actual['files'] if row['path'] != 'ADMISSION.json'}
    require(rows == manifest['files'] and sum(row['bytes'] for row in rows.values()) == manifest['payloadBytes'],
        'compatibility-public-original-union')
    return read_json(directory / 'qualified.json', PUBLIC_METADATA_RESERVE)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    public = commands.add_parser('retain')
    public.add_argument('--source', type=Path, required=True)
    public.add_argument('--output', type=Path, required=True)
    rollup = commands.add_parser('assemble')
    rollup.add_argument('--inputs', type=Path, required=True)
    rollup.add_argument('--source-commit', required=True)
    rollup.add_argument('--output', type=Path, required=True)
    rollup.add_argument('--preserved', type=Path)
    rollup.add_argument('--diagnostics', type=Path)
    args = parser.parse_args()
    if args.command == 'retain': retain(args.source, args.output)
    else:
        cells = set(CELLS) - set(PRESERVED_CELLS) if args.preserved is not None else set(CELLS)
        require({path.name for path in args.inputs.iterdir()} == cells,
            'compatibility-matrix-exact-artifact-directories')
        result = assemble({cell: read_retained(args.inputs / cell) for cell in cells},
            source_commit=args.source_commit, preserved_directory=args.preserved, diagnostic_output=args.diagnostics)
        write_json(args.output, result)
