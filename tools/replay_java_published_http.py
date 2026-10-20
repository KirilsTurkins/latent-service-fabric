"""Fresh published-client Java builds with separately authenticated native history."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment
from tools.java_replay_materials import prepare, verify_prepared, native_products
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_published_http import MAX_SECONDS, execute
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, write_json


def run(output, prepared, wasi_sdk):
    require(sys.platform == 'linux', 'java-published-replay-linux-required')
    require(output != ROOT and ROOT not in output.parents, 'java-published-replay-outside-source')
    native_source = verify_prepared(prepared)
    output = fresh(output)
    binaries = native_products(prepared)
    products = {name: file_identity(path) for name, path in binaries.items()}
    diagnostic = {name: file_identity(ROOT / name) for name in
                  ('tools/java_replay_materials.py', 'tools/replay_java_published_http.py')}
    environment = build_environment(output)
    if 'JAVA_HOME' in os.environ:
        environment['JAVA_HOME'] = os.environ['JAVA_HOME']
    commands = Commands(ROOT, fresh(output / 'commands'), environment,
                        deadline_seconds=MAX_SECONDS, command_seconds=300)
    try:
        result = execute(commands, binaries, wasi_sdk, output / 'campaign')
        require(result['status'] == 'passed' and result['publishedClientInvocations'] == 26
                and result['nativeProducts'] == products
                and native_source == verify_prepared(prepared)
                and products == {name: file_identity(path) for name, path in binaries.items()}
                and diagnostic == {name: file_identity(ROOT / name) for name in diagnostic},
                'java-published-replay-final-material-drift')
        result.update(schemaVersion='latent.java.published-http.replay-qualification.v1',
                      nativeSource=native_source, nativeRecompiled=False,
                      productionNativeTupleRecreated=False, diagnosticMaterials=diagnostic,
                      fixtureSource=subprocess.check_output(
                          ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip())
        write_json(output / 'qualification.json', result)
        return result
    except BaseException:
        try:
            write_json(output / 'FAILED.json', {'status': 'failed',
                'phase': 'current-published-client-campaign', 'full688Qualification': False,
                'full741Qualification': False, 'nativeRecompiled': False})
        except Exception:
            pass
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--wasi-sdk', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(sys.platform == 'linux', 'java-published-replay-linux-required')
    output = args.output.resolve()
    require(output != ROOT and ROOT not in output.parents, 'java-published-replay-outside-source')
    if args.prepare:
        require(args.prepared is None and args.wasi_sdk is None, 'java-published-replay-prepare-only')
        prepare(output)
    else:
        require(args.prepared is not None and args.wasi_sdk is not None,
                'java-published-replay-explicit-inputs-required')
        result = run(output, args.prepared.resolve(strict=True), args.wasi_sdk.resolve(strict=True))
        print(json.dumps({'status': result['status'], 'invocations': result['publishedClientInvocations']}))
