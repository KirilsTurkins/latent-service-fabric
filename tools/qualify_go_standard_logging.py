"""Sign ordinary captured Go logging using this run's frozen native products."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.go_capsule_build import build
from tools.go_capsule_project import create
from tools.go_standard_logging_probe import LIBRARY, install
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_go_standard_http import NATIVE_NAMES
from tools.qualify_rust_capsules import inputs
from tools.run_rust_capsule_workflow import run
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, TEMPLATES, digest, fresh, read_json, snapshot, inventory, write_json

MATERIALS = ('tools/qualify_go_standard_logging.py', 'tools/go_standard_logging_probe.py',
             'tools/go_guest/standard_log.py', 'tools/run_rust_capsule_workflow.py')


def frozen(native: Path):
    receipt = read_json(native / 'qualification.json')
    require(receipt.get('schemaVersion') == 'latent.go-capsule.qualification.v1'
            and receipt.get('status') == 'passed'
            and receipt.get('node', {}).get('status') == 'passed'
            and len(receipt.get('node', {}).get('invocations', [])) >= 27
            and read_json(native / 'source-inputs.json') == inputs('go')
            and digest((native / 'source-inputs.json').read_bytes()) == receipt.get('sourceIdentityDigest'),
            'go-log-current-normal-qualification-required')
    products = {name: native / 'native-binaries' / key.replace('/', '-') for name, key in NATIVE_NAMES.items()}
    require(all(file_identity(path, 512 * 1024**2) == receipt['binaries'][NATIVE_NAMES[name]]
                for name, path in products.items()), 'go-log-frozen-native-product-mismatch')
    companions = [native / 'builds' / name for name in sorted(set(TEMPLATES) - {'greeting'})]
    require(all(read_json(path / 'BUILD-COMPLETE.json') == receipt['builds'][path.name]
                for path in companions), 'go-log-companion-build-mismatch')
    return receipt, products, companions


def reference(output, commands, go):
    directory = fresh(output)
    (directory / 'ordinary').mkdir()
    (directory / 'go.mod').write_text('module reference.local/logging\n\ngo 1.27.2\n', encoding='utf-8')
    (directory / 'ordinary/logging.go').write_text(LIBRARY, encoding='utf-8')
    (directory / 'main.go').write_text('package main\nimport ("fmt"; "os"; '
        '"reference.local/logging/ordinary")\nfunc main() { '
        'if ordinary.Exercise(os.Args[1]) != "1" { panic("native reference changed") }; '
        'fmt.Print("REFERENCE-PASS") }\n', encoding='utf-8')
    before, commands.root = commands.root, directory
    try:
        binary = directory / 'reference'
        commands.run('reference-build', go, 'build', '-o', binary, '.')
        for mode in ('initializer', 'fmt', 'stderr', 'log', 'zero'):
            raw = commands.run('reference-' + mode, binary, mode)
            require(raw.startswith(b'ordinary library initializer') and raw.endswith(b'REFERENCE-PASS'),
                    'go-log-native-reference-changed')
    finally:
        commands.root = before
    return {'kind': 'native-reference', 'librarySourceDigest': digest(LIBRARY.encode()),
            'cases': ['initializer', 'fmt', 'stderr', 'log', 'zero'], 'componentExecution': False}


def qualify(output: Path, native: Path):
    output = fresh(output)
    require(output != ROOT and ROOT not in output.parents, 'go-log-output-must-be-outside-runtime')
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1100, command_seconds=600)
    materials = {name: file_identity(ROOT / name) for name in MATERIALS}
    stage, record = 'frozen-native-inputs', {'schemaVersion': 'latent.go.standard-logging.qualification.v1',
        'status': 'in-progress', 'materials': materials, 'publisherAuthenticated': False,
        'releasePublication': 'not-performed', 'fullTicketQualification': False,
        'asyncBufferedLogging': 'not-qualified', 'runtimePanicStderr': 'not-supported'}
    try:
        receipt, products, companions = frozen(native)
        record['nativeQualification'] = file_identity(native / 'qualification.json')
        record['nativeBinaries'] = receipt['binaries']
        record['fullNormalBaseline'] = {'status': receipt['node']['status'],
            'invocations': len(receipt['node']['invocations']),
            'sourceIdentityDigest': receipt['sourceIdentityDigest'],
            'qualification': record['nativeQualification']}
        go = Path(shutil.which('go') or 'missing-pinned-go').resolve(strict=True)
        go_before = file_identity(go)
        stage = 'native-reference'
        record['reference'] = reference(output / 'reference', commands, go)
        stage = 'normal-local-dependency-capture'
        application = create(output / 'application', 'greeting')
        record['capture'] = install(application, output / 'outside-library', go)
        write_json(output / 'capture.json', record['capture'])
        stage = 'isolated-offline-component-build'
        before = inventory(snapshot(application))
        built = build(application, output / 'build', products['capsule_contracts'], products['package'],
                      'https://github.com/KirilsTurkins/latent-service-fabric')
        require(before == inventory(snapshot(application)), 'go-log-application-source-changed')
        require(read_json(built / 'application-dependencies.json')['networkResolution'] is False,
                'go-log-offline-captured-build-required')
        stage = 'separate-demo-signing'
        require(frozen(native)[0] == receipt, 'go-log-original-native-inputs-changed')
        commands.run('demo-sign', products['capsule_authoring'], 'demo-sign', output / 'signed', built, *companions)
        stage = 'signed-enforced-node'
        node = run(products['latent'], products['latentd'], output / 'signed', output / 'node',
                   language='go', go_standard_logging=True)
        require(node['status'] == 'passed' and node.get('goStandardLogging', {}).get('status') == 'passed',
                'go-log-actual-signed-programme-required')
        stage = 'final-integrity'
        require(frozen(native)[0] == receipt and materials == {name: file_identity(ROOT / name) for name in MATERIALS}
                and go_before == file_identity(go) and time.monotonic() < commands.deadline,
                'go-log-qualification-materials-changed')
        record.update(status='passed', component=read_json(built / 'BUILD-COMPLETE.json'),
                      nodeReceipt=file_identity(output / 'node/workflow.json'), commands=commands.records,
                      compiler=go_before, scope='ordinary captured Go fmt/log/os initialization, errors and fresh invocation')
        write_json(output / 'qualification.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__, commands=commands.records)
        write_json(output / 'FAILED.json', record)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-qualification', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps({'status': qualify(args.output, args.native_qualification)['status']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
