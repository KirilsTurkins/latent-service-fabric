#!/usr/bin/env python3
"""Run the current Go timer runtime as core Wasm against a bounded mock host.

This reuses an already prepared pinned compiler and an existing qualification's
vendored dependency. It does not sign a component or claim real provider/Store
retirement. The normal Go qualification owns the durable execution.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.go_guest import runtime
from tools.rust_capsule_project import ROOT, inventory, snapshot


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(go, vendor, cache, output, source_commit):
    if re.fullmatch(r'[0-9a-f]{40}', source_commit) is None:
        raise ValueError('go-timer-control-source-commit-invalid')
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True,
                          text=True, check=True).stdout.strip()
    if head != source_commit:
        raise ValueError('go-timer-control-source-commit-drift')
    inputs = ['sdk/go-guest/runtime', 'sdk/go-guest/runtime-deps', 'tools/go_guest',
              'tools/go_timer_runtime_control.py', 'tools/rust_capsule_project.py',
              'tools/tests/fixtures/go_timer_runtime_mock.go.txt',
              'tools/tests/fixtures/go_timer_runtime_mock_host.js']
    status = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=all', '--', *inputs],
                            cwd=ROOT, capture_output=True, text=True, check=True)
    if status.stdout:
        raise ValueError('go-timer-control-source-inputs-dirty')
    go, vendor, cache, output = map(lambda path: path.resolve(), (go, vendor, cache, output))
    goroot = go.parent.parent
    if (goroot / 'VERSION').read_text(encoding='utf-8').splitlines()[0] != 'go1.27.4':
        raise ValueError('go-timer-control-compiler-version-drift')
    runtime.checked_sources(goroot, runtime.PREIMAGES)
    if not cache.is_dir():
        raise ValueError('go-timer-control-existing-cache-required')
    before = snapshot(vendor)
    if not before or 'modules.txt' not in before:
        raise ValueError('go-timer-control-vendor-incomplete')
    output.mkdir(parents=True, exist_ok=False)
    project = output / 'project'
    project.mkdir()
    shutil.copytree(vendor, project / 'vendor')
    if snapshot(project / 'vendor') != before:
        raise ValueError('go-timer-control-vendor-copy-drift')
    for name in ('go.mod', 'go.sum'):
        (project / name).write_bytes((ROOT / 'sdk/go-guest/runtime-deps' / name).read_bytes())
    fixture = ROOT / 'tools/tests/fixtures/go_timer_runtime_mock.go.txt'
    host = ROOT / 'tools/tests/fixtures/go_timer_runtime_mock_host.js'
    (project / 'main.go').write_bytes(fixture.read_bytes())
    overlay = runtime.overlay(goroot, output / 'overlay',
        project / 'vendor/go.bytecodealliance.org/pkg', sdk=ROOT / 'sdk/go-guest',
        activation=True, checkpoints=True, timers=True, initializers=True,
        managed_idle=True, queued_work=True, bounded_stacks=True)
    env = dict(os.environ, GOROOT=str(goroot), GO111MODULE='on', GOENV='off',
        GOFLAGS='-mod=vendor -overlay=' + str(overlay), GOWORK='off', GOTOOLCHAIN='local',
        GOMAXPROCS='2', GOCACHE=str(cache), CGO_ENABLED='0', GOOS='wasip1', GOARCH='wasm',
        GOPROXY='off', GOSUMDB='off')
    artifact = output / 'timer-control.wasm'
    build = subprocess.run([str(go), 'build', '-buildmode=c-shared', '-ldflags=-checklinkname=0',
                            '-o', str(artifact), '.'], cwd=project, env=env,
                           capture_output=True, text=True, timeout=240)
    (output / 'build.stdout.log').write_text(build.stdout, encoding='utf-8')
    (output / 'build.stderr.log').write_text(build.stderr, encoding='utf-8')
    if build.returncode:
        raise RuntimeError('go-timer-control-build-failed: ' + build.stderr[-4000:])
    node = shutil.which('node')
    if node is None:
        raise ValueError('go-timer-control-node-required')
    result = subprocess.run([node, str(host), str(artifact)], cwd=output,
                            capture_output=True, text=True, timeout=60)
    (output / 'host.stdout.log').write_text(result.stdout, encoding='utf-8')
    (output / 'host.stderr.log').write_text(result.stderr, encoding='utf-8')
    if result.returncode or 'REAL_RUNTIME_WITH_MOCK_HOST=PASS' not in result.stdout:
        raise RuntimeError('go-timer-control-host-failed: ' + (result.stdout + result.stderr)[-4000:])
    receipt = {
        'formatVersion': 1,
        'qualification': 'actual-go-core-wasm-with-mock-host',
        'runtimeProfile': 'go-component-activation-v7',
        'signedComponent': False,
        'sourceCommit': source_commit,
        'goBinarySha256': sha(go.read_bytes()),
        'goTimeSourceSha256': sha((goroot / 'src/runtime/time.go').read_bytes()),
        'emittedTimeSourceSha256': sha((output / 'overlay/runtime_time.go').read_bytes()),
        'fixtureSha256': sha(fixture.read_bytes()),
        'mockHostSha256': sha(host.read_bytes()),
        'vendorManifestSha256': sha(inventory(before)),
        'wasmSha256': sha(artifact.read_bytes()),
        'result': 'passed',
    }
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('go', 'vendor', 'cache', 'output'):
        parser.add_argument('--' + option, required=True, type=Path)
    parser.add_argument('--source-commit', required=True)
    print(json.dumps(run(**vars(parser.parse_args())), sort_keys=True))
