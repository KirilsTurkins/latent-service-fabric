"""Compile a new application fixture using the original qualified native tuple."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.go_standard_http_node import run
from tools.go_standard_http_project import project
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_go_standard_http import NATIVE_NAMES
from tools.rust_capsule_project import ROOT, digest, fresh, read_json, write_json


def qualify(prepared, native_qualification, output):
    output = fresh(output)
    record = {'schemaVersion': 'latent.go.http-adversarial.qualification.v1', 'status': 'in-progress',
        'componentCompilationPerformed': True, 'nativeCompilationPerformed': False,
        'commandLimits': {'overallSeconds': 1200, 'compileSeconds': 900, 'nodeSeconds': 300}, 'fullTicketQualification': False}
    materials = {name: file_identity(ROOT / name) for name in (
        'tools/qualify_go_http_adversarial.py', 'tools/go_http_adversarial.py',
        'tools/fixtures/go-http-adversarial/main.go')}
    record['materials'] = materials
    deadline = time.monotonic() + 1200
    try:
        standard = read_json(prepared / 'qualification.json')
        require(standard['status'] == standard['node']['status'] == 'passed'
                and standard['node']['suite'] == 'standard' and len(standard['node']['cases']) == 33,
                'adversarial-go-original-33-required')
        artifact = prepared / 'build'
        require(standard['node']['artifact'] == {
            name: file_identity(artifact / name) for name in standard['node']['artifact']},
            'adversarial-go-compiled-artifact-changed')
        require(standard['node']['sources'] == {
            name: file_identity(ROOT / name) for name in standard['node']['sources']},
            'adversarial-go-qualified-source-changed')
        native_receipt = native_qualification / 'qualification.json'
        require(file_identity(native_receipt) == standard['nativeQualification'],
                'adversarial-go-native-qualification-changed')
        native = {name: native_qualification / 'native-binaries' / key.replace('/', '-')
                  for name, key in NATIVE_NAMES.items()}
        identities = {name: file_identity(path, 512 * 1024 * 1024) for name, path in native.items()}
        require(identities == standard['binaries'], 'adversarial-go-native-product-changed')
        record['precedingQualification'] = file_identity(prepared / 'qualification.json')
        app = project(output / 'project')
        source = (ROOT / 'tools/fixtures/go-http-adversarial/main.go').read_bytes()
        (app / 'src/main.go').write_bytes(source)
        lock = read_json(app / 'sdk-lock.json')
        lock['template']['sourceDigest'] = digest(source)
        (app / 'sdk-lock.json').write_bytes((json.dumps(lock, indent=2) + '\n').encode())
        command = [sys.executable, str(ROOT / 'tools/go_capsule.py'), 'build', str(app),
            '--output', str(output / 'build'), '--repository',
            'https://github.com/KirilsTurkins/latent-service-fabric',
            '--contracts-tool', str(native['capsule_contracts']), '--packager', str(native['package'])]
        built = run_bounded_result(command, ROOT, build_environment(output),
            timeout_seconds=min(900, deadline - time.monotonic()), max_output_bytes=2 * 1024 * 1024)
        for name in ('stdout', 'stderr'):
            (output / ('compiler.' + name + '.txt')).write_bytes(getattr(built, name))
        require(built.returncode == 0, 'adversarial-go-component-build-failed')
        record['build'] = read_json(output / 'build/BUILD-COMPLETE.json')
        record['node'] = run(output / 'build',
            {name: native[name] for name in ('latent', 'latentd', 'capsule_authoring')},
            output / 'node', suite='adversarial', deadline=deadline)
        require(record['node']['status'] == 'passed' and len(record['node']['cases']) == 9,
                'adversarial-go-nine-cases-required')
        require(record['precedingQualification'] == file_identity(prepared / 'qualification.json')
                and identities == {name: file_identity(path, 512 * 1024 * 1024)
                                   for name, path in native.items()}
                and file_identity(native_receipt) == standard['nativeQualification']
                and materials == {name: file_identity(ROOT / name) for name in materials},
                'adversarial-go-final-input-drift')
        record['status'] = 'passed'
        write_json(output / 'qualification.json', record)
        return record
    except BaseException:
        record['status'] = 'failed'
        write_json(output / 'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--native-qualification', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.prepared.resolve(), args.native_qualification.resolve(), args.output.resolve())))
