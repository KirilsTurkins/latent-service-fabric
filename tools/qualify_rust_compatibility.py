"""Signed ordinary Rust incompatibility controls over this run's existing native tuple."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
import tomllib

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import guest_compatibility as compatibility
from tools.build_observation import build_environment, resolve_tools
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_rust_capsules import inputs
from tools.qualify_rust_git_components import COMPANIONS, prepared_inputs
from tools.run_rust_capsule_workflow import run
from tools.rust_capsule_build import Commands, build
from tools.rust_capsule_project import ROOT, create, digest, fresh, inventory, read_json, snapshot, write_json
from tools.rust_compatibility_probe import CALLBACK_SOURCE, LIBRARY, install

MATERIALS = ('tools/qualify_rust_compatibility.py', 'tools/rust_compatibility_probe.py',
             'tools/guest_compatibility.py', 'tools/guest_compatibility_outcomes.py',
             'tools/run_rust_capsule_workflow.py')


def reference(output, commands, rustc):
    """Native controls identify the reference behavior; they grant no guest support."""
    directory = fresh(output)
    (directory / 'callback.rs').write_text(CALLBACK_SOURCE, encoding='utf-8')
    (directory / 'library.rs').write_text(LIBRARY.replace('outside_compatibility_callback::', 'callback::'), encoding='utf-8')
    (directory / 'main.rs').write_text('mod callback;\ninclude!("library.rs");\n'
        'fn main() { let mode = std::env::args().nth(1).unwrap(); println!("{}", describe(&mode)); }\n', encoding='utf-8')
    binary = directory / ('reference.exe' if os.name == 'nt' else 'reference')
    commands.run('reference-compile', rustc, '--edition=2021', directory / 'main.rs', '-o', binary)
    results = {}
    for case, expected in (('caught', b'spawned:7'), ('eliminated', b'native-thread:7'), ('uncaught', b'spawned:7')):
        raw = commands.run('reference-' + case, binary, case)
        require(raw.strip() == expected, 'compatibility-native-reference-result')
        results[case] = expected.decode()
    return {'profile': 'native-reference', 'results': results, 'compiler': file_identity(rustc),
            'librarySourceDigest': digest(LIBRARY.encode()), 'callbackSourceDigest': digest(CALLBACK_SOURCE.encode())}


def execution_report(build_output, captured, node):
    original = compatibility.read((build_output / 'compatibility-report.json').read_bytes())
    releases = [row for row in node['releaseSet']['releases'] if row['name'] == 'my-greeting']
    require(len(releases) == 1 and releases[0]['componentDigest'] == original['componentDigest'],
            'compatibility-signed-component-mismatch')
    require(node.get('rustCompatibility', {}).get('status') == 'passed'
            and [row['outcome'] for row in node['rustCompatibility']['cases']]
                == ['unsupported-thread', 'eliminated', 'terminal-trap', 'unsupported-thread'],
            'compatibility-signed-probe-outcomes-required')
    # These are fixture-specific observations bound to exact captured source.
    # No arbitrary emitted graph or generic trap is promoted to API evidence.
    reached = compatibility.finding('unsupported-reached', 'invocation', 'actual-component',
        operation='std::thread::Builder.spawn', owner_issue=743,
        package_digest=captured['libraries'][captured['package']]['treeDigest'],
        source_digest=captured['librarySourceDigest'], symbol='describe')
    unknown = compatibility.finding('unresolved-behavior', 'invocation', 'actual-component',
        operation='uncaught-thread-spawn', owner_issue=743, source_digest=captured['librarySourceDigest'])
    return compatibility.report('rust', original['sourceDigest'], original['componentDigest'],
        original['runtimeProfile'], original['inputs'], [*original['findings'], reached, unknown])


def qualify(prepared: Path, output: Path):
    output = fresh(output)
    require(output != ROOT and ROOT not in output.parents, 'compatibility-output-must-be-outside-runtime')
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1100, command_seconds=600)
    materials = {name: file_identity(ROOT / name) for name in MATERIALS}
    stage = 'prepared-inputs'
    try:
        before, qualified, products = prepared_inputs(prepared)
        if os.name == 'posix':
            for binary in products.values():
                binary.chmod(0o700)
        paths, tools = resolve_tools(tomllib.loads((ROOT / 'tools/toolchain.toml').read_text()), ROOT, commands.environment)
        require(next(row for row in tools if row['name'] == 'cargo')
                == next(row for row in qualified['tools'] if row['name'] == 'cargo'),
                'compatibility-prepared-compiler-mismatch')
        stage = 'native-reference'
        observed_reference = reference(output / 'reference', commands, paths['rustc'])
        stage = 'normal-captured-dependency'
        project = create(output / 'application', 'greeting')
        captured = install(project, output / 'outside', paths['cargo'])
        write_json(output / 'capture.json', captured)
        stage = 'isolated-offline-component'
        source = inventory(snapshot(project))
        built = build(project, output / 'build', products['examples/capsule_contracts'], products['examples/package'],
                      'https://github.com/KirilsTurkins/latent-service-fabric', offline=True)
        require(inventory(snapshot(project)) == source
                and read_json(built / 'cargo-inputs.json')['networkResolution'] is False,
                'compatibility-offline-source-changed')
        stage = 'signing'
        require(prepared_inputs(prepared)[:2] == (before, qualified), 'compatibility-prepared-inputs-changed')
        commands.run('sign-compatibility-fixture', products['examples/capsule_authoring'], 'demo-sign', output / 'signed',
                     built, *(prepared / 'builds' / name for name in COMPANIONS))
        stage = 'signed-node'
        node = run(products['latent'], products['latentd'], output / 'signed', output / 'node',
                   language='rust', rust_compatibility=True)
        require(node['status'] == 'passed', 'compatibility-signed-node-not-passed')
        report = execution_report(built, captured, node)
        write_json(output / 'compatibility-execution-report.json', report)
        stage = 'final-integrity'
        require(inputs('rust') == before and materials == {name: file_identity(ROOT / name) for name in MATERIALS}
                and all(file_identity(binary, 512 * 1024 * 1024) == qualified['binaries'][name]
                        for name, binary in products.items()) and time.monotonic() < commands.deadline,
                'compatibility-qualification-inputs-changed')
        result = {'formatVersion': 1, 'status': 'passed', 'scope': 'signed captured Rust unsupported-operation diagnostics',
            'materials': materials, 'sourceIdentityDigest': qualified['sourceIdentityDigest'],
            'nativeBinaries': qualified['binaries'], 'capture': captured, 'reference': observed_reference,
            'component': read_json(built / 'BUILD-COMPLETE.json'), 'reportIdentity': report['identity'],
            'nodeReceipt': file_identity(output / 'node/workflow.json'), 'commands': commands.records,
            'publisherAuthenticated': False, 'releasePublication': 'not-performed',
            'initializationFailure': 'not-tested', 'compilerElimination': 'cfg-selected-fixture-only',
            'sixLanguageMatrix': 'not-complete', 'retrySafety': 'unknown'}
        write_json(output / 'qualification.json', result)
        return result
    except BaseException as error:
        write_json(output / 'FAILED.json', {'status': 'failed', 'stage': stage,
                   'commands': commands.records, 'errorCategory': type(error).__name__, 'materials': materials})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared-qualification', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps({'status': qualify(args.prepared_qualification, args.output)['status']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
