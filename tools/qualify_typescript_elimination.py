"""Two normal TypeScript builds differing by one root edge; finite compiler and actual witnesses."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import time

if __package__ in {None, ''}:
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import c_thread_admission_native_products as native
from tools import guest_compatibility as compatibility
from tools.build_observation import build_environment
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, source_identity
from tools.qualify_sdk_explicit_fallback import MATERIALS as SHARED_MATERIALS, compiled, selected_tools
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_json, snapshot, write_json
from tools.typescript_elimination_fixture import CALLBACK, project, select_root_edge
from tools.typescript_elimination_evidence import contribution
from tools.typescript_elimination_node import run
from tools.typescript_guest.build import RECIPE
from tools.typescript_guest.compiler import Compiler

MATERIALS = tuple(dict.fromkeys((*SHARED_MATERIALS, *RECIPE,
    '.github/workflows/typescript-elimination.yml',
    'tools/qualify_typescript_elimination.py', 'tools/typescript_elimination_fixture.py',
    'tools/typescript_elimination_node.py', 'tools/tests/test_typescript_elimination.py', 'tools/typescript_elimination_evidence.py')))


def materials():
    require(len(MATERIALS) == len(set(MATERIALS)) <= 256, 'typescript-fallback-material-count-bound')
    rows = {name: file_identity(ROOT / name, 1024**2) for name in MATERIALS}
    require(sum(row['bytes'] for row in rows.values()) <= 16 * 1024**2, 'typescript-fallback-material-byte-bound')
    return rows


def qualify(products: Path, compiler_tools: Path, output: Path):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13) and os.geteuid() != 0,
        'typescript-fallback-unprivileged-linux-python313')
    compiler_tools = compiler_tools.resolve(strict=True)
    output = output.absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents
        and not output.is_relative_to(compiler_tools) and not compiler_tools.is_relative_to(output),
        'typescript-fallback-separated-output')
    output = fresh(output)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1100, command_seconds=600)
    origin = native.verify_prepared(products)
    binaries = native.native_products(products)
    tools = selected_tools(binaries)
    for binary in binaries.values(): binary.chmod(0o700)
    identities = {name: file_identity(path, 512 * 1024**2) for name, path in binaries.items()}
    compiler = object.__new__(Compiler)
    compiler_identity = compiler.identity(compiler_tools)
    native_inputs = read_json(products / 'source-inputs.json')
    source, before = source_identity(ROOT), materials()
    record = {'schemaVersion': 'latent.typescript.elimination.qualification.v1', 'status': 'incomplete',
        'eliminationScope': 'one-exact-esbuild-application-module', 'arbitraryApiClassification': 'unknown',
        'nativeOrigin': origin, 'nativeProductIdentities': identities,
        'perProductCompilation': native_inputs['perProductCompilation'],
        'consumerNativeSource': source, 'consumerNativeSourceIsProductCompilationClaim': False,
        'materials': before, 'compilerInputs': compiler_identity, 'guestBuildsRequested': 2,
        'nativeProductsRebuilt': False, 'javascriptEngineRebuilt': False,
        'clockGrantAdded': False, 'transparentClockCompatibility': False, 'fullTicketQualification': False}
    stage = 'ordinary-transitive-application-capture'
    try:
        app, fixture = project(output / 'application', output / 'outside')
        initial = snapshot(app)
        record['fixture'] = fixture
        record['variants'] = {}
        for label, selected in (('eliminated', False), ('reached', True)):
            if selected:
                record['counterfactual'] = select_root_edge(app)
            current = snapshot(app)
            require(set(current) == set(initial) and all(current[name] == initial[name]
                for name in initial if name != 'src/main.ts'), 'elimination-exact-libraries-and-single-root-edge')
            captured = inventory(current)
            stage = label + '-normal-compiler-package'
            artifact = output / label / 'build'
            artifact.parent.mkdir()
            commands.run(stage, sys.executable, '-B', ROOT / 'tools/typescript_capsule.py', 'build', app,
                '--output', artifact, '--repository', 'https://github.com/KirilsTurkins/latent-service-fabric',
                '--tools', compiler_tools, '--contracts-tool', tools['capsule_contracts'], '--packager', tools['package'])
            build = compiled(artifact, captured)
            witness = contribution(read_json(artifact / 'bundle-selected-inputs.json'), selected=selected)
            stage = label + '-normal-neutral-signing'
            signed = output / label / 'signed'
            commands.run(stage, tools['capsule_authoring'], 'demo-sign-neutral-resources', signed, artifact)
            stage = label + '-four-actual-outcomes'
            node = run('typescript', artifact, signed, binaries, output / label / 'node', commands.deadline, reached=selected)
            require(node['status'] == 'passed' and len(node['cases']) == 4
                and inventory(snapshot(app)) == captured and compiled(artifact, captured) == build,
                'elimination-four-actual-outcomes-and-original-build-identity')
            record['variants'][label] = {'build': build, 'compilerModuleWitness': witness,
                'bundleObservation': file_identity(artifact / 'bundle-selected-inputs.json'),
                'node': file_identity(output / label / 'node/qualified.json')}
            write_json(output / ('observed-variants-' + label + '.json'), record['variants'])
        # No API-elimination report is emitted before BOTH actual variants pass.
        require(set(record['variants']) == {'eliminated', 'reached'}, 'elimination-both-real-variants-before-reports')
        for label, selected in (('eliminated', False), ('reached', True)):
            build = record['variants'][label]['build']
            artifact = output / label / 'build'
            source_digest = build['sourceInputs']['sha256']
            report = compatibility.report('typescript', source_digest, build['component']['sha256'],
                'spidermonkey-public-sync-v1',
                [{'kind': 'application', 'digest': source_digest},
                 {'kind': 'compiler', 'digest': file_identity(artifact / 'compiler-inputs.json')['sha256']}],
                [compatibility.finding('unsupported-reached' if selected else 'unsupported-eliminated',
                    'invocation' if selected else 'compile', 'actual-component' if selected else 'compiler',
                    operation='Date.now', owner_issue=745, source_digest=digest(CALLBACK.encode()),
                    symbol='unsupportedClockCallback'),
                 compatibility.finding('unresolved-behavior', 'invocation', 'actual-component',
                    operation='uncaught-fixture-trap-cause-unknown'),
                 compatibility.finding('lifecycle-unproven', 'retirement', 'not-evaluated',
                    operation='arbitrary-library-worker-drain')])
            write_json(output / label / 'compatibility-execution-report.json', report)
            record['variants'][label]['executionReport'] = file_identity(output / label / 'compatibility-execution-report.json')
        stage = 'final-source-products-and-retirement'
        require(materials() == before and source_identity(ROOT) == source and native.verify_prepared(products) == origin
            and compiler.identity(compiler_tools) == compiler_identity
            and {name: file_identity(path, 512 * 1024**2) for name, path in binaries.items()} == identities
            and time.monotonic() < commands.deadline, 'typescript-fallback-final-source-products-and-total-bound')
        record.update(status='passed', attempts=8, commands=commands.records)
        write_json(output / 'qualification.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__, commands=commands.records)
        try: write_json(output / 'FAILED.json', record)
        except BaseException: pass
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('native-products', 'tools', 'output'): parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = qualify(args.native_products, args.tools, args.output)
    print(json.dumps({'status': result['status'], 'attempts': result['attempts']}))
