"""Build/sign/execute default HttpClient using already frozen ordinary products."""
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
from tools.dotnet_standard_http_project import project
from tools.dotnet_standard_http_node import run
from tools.phase2_operator_process import read_json, require, write_json
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, fresh


NATIVE_NAMES = {'latent': 'latent', 'latentd': 'latentd', 'package': 'examples/package',
                'capsule_contracts': 'examples/capsule_contracts', 'capsule_authoring': 'examples/capsule_authoring'}


def qualify(output: Path, tools: Path, native_qualification: Path):
    output = fresh(output)
    deadline = time.monotonic()+1200
    record = {'schemaVersion': 'latent.dotnet.standard-http.build-qualification.v1', 'status': 'in-progress',
        'commandLimits': {'overallSeconds': 1200, 'compileSeconds': 900, 'nodeSeconds': 300},
        'defaultClient': 'System.Net.Http.HttpClient', 'applicationHandlerInjection': False,
        'fullTicketQualification': False}
    stage = 'native-products'
    try:
        receipt_path = native_qualification/'qualification.json'
        receipt = read_json(receipt_path)
        require(receipt['status'] == 'passed', 'standard-dotnet-normal-native-qualification-required')
        before = file_identity(receipt_path)
        binaries = {name: native_qualification/'native-binaries'/key.replace('/', '-')
                    for name, key in NATIVE_NAMES.items()}
        identities = {name: file_identity(path, 512*1024*1024) for name, path in binaries.items()}
        require(all(identities[name] == receipt['binaries'][key] for name, key in NATIVE_NAMES.items()),
                'standard-dotnet-frozen-native-products-mismatch')
        record.update(nativeQualification=before, binaries=identities)
        stage = 'source-capture'
        app = project(output/'project')
        stage = 'normal-native-aot-build'
        command = [sys.executable, str(ROOT/'tools/dotnet_capsule.py'), 'build', str(app),
            '--tools', str(tools), '--output', str(output/'build'), '--repository',
            'https://github.com/KirilsTurkins/latent-service-fabric',
            '--contracts-tool', str(binaries['capsule_contracts']), '--packager', str(binaries['package'])]
        write_json(output/'compiler-command.json', {'command': command, 'maximumSeconds': 900})
        result = run_bounded_result(command, ROOT, build_environment(output),
            timeout_seconds=min(900, deadline-time.monotonic()), max_output_bytes=2*1024*1024)
        for name in ('stdout', 'stderr'):
            (output/('compiler.'+name+'.txt')).write_bytes(getattr(result, name))
        require(result.returncode == 0, 'standard-dotnet-component-build-failed')
        stage = 'signed-ordinary-node'
        record['node'] = run(output/'build', {name: binaries[name] for name in ('latent', 'latentd', 'capsule_authoring')},
                             output/'node', deadline=deadline)
        stage = 'final-integrity'
        require(before == file_identity(receipt_path)
                and identities == {name: file_identity(path, 512*1024*1024) for name, path in binaries.items()},
                'standard-dotnet-frozen-native-products-changed')
        record['status'] = 'passed'
        write_json(output/'qualification.json', record)
        return record
    except BaseException:
        record.update(status='failed', stage=stage)
        write_json(output/'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--tools', required=True, type=Path)
    parser.add_argument('--native-qualification', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(qualify(args.output.resolve(), args.tools.resolve(), args.native_qualification.resolve())))
