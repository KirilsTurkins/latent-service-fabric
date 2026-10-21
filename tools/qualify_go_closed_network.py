#!/usr/bin/env python3
"""One bounded upstream/closed WASI reference; never an LSF execution receipt."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import file_identity
from tools.go_guest.runtime import FAKE_NETWORK_SHA256, checked_sources, closed_network_source
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, write_json

FIXTURE = 'tools/tests/fixtures/go-closed-network'
RECIPE = ('tools/qualify_go_closed_network.py', 'tools/go_guest/runtime.py',
          FIXTURE + '/reference.go.txt', FIXTURE + '/run-reference.mjs')


def outcomes(original: bytes, corrected: bytes) -> dict:
    if original != b'tcp=fake-listener\nudp=fake-listener\n':
        raise ValueError('Go-closed-network-upstream-counterfactual-missing')
    if corrected != b'tcp=unsupported\nudp=unsupported\n':
        raise ValueError('Go-closed-network-standard-unsupported-missing')
    return {'upstream': ['tcp=fake-listener', 'udp=fake-listener'],
            'corrected': ['tcp=unsupported', 'udp=unsupported']}


def qualify(output: Path) -> dict:
    output = fresh(output)
    environment = dict(os.environ)
    commands = Commands(output, output, environment, deadline_seconds=600, command_seconds=300)
    tools = {}
    for name in ('go', 'node'):
        path = shutil.which(name, path=environment['PATH'])
        if path is None:
            raise ValueError('Go-closed-network-missing-tool:' + name)
        tools[name] = Path(path).resolve(strict=True)
    before = {name: file_identity(path, name) for name, path in tools.items()}
    recipe = inventory({name: read_file(ROOT / name) for name in RECIPE})
    record = {'schemaVersion': 'latent.go.closed-network.reference.v1', 'status': 'in-progress',
        'qualification': 'owned-upstream-wasi-reference-only', 'signedLsfExecution': False,
        'providerInstalled': False, 'networkReadiness': False, 'recipeDigest': digest(recipe),
        'tools': before, 'commandLimits': {'overallSeconds': 600, 'perCommandSeconds': 300}}
    (output / 'recipe-inputs.json').write_bytes(recipe)
    try:
        if commands.run('go-version', tools['go'], 'version').split() != [b'go', b'version', b'go1.27.3', b'linux/amd64']:
            raise ValueError('Go-closed-network-compiler-identity')
        if commands.run('node-version', tools['node'], '--version').strip() != b'v24.19.0':
            raise ValueError('Go-closed-network-reference-engine-identity')
        goroot = Path(commands.run('go-root', tools['go'], 'env', 'GOROOT').decode().strip())
        original = checked_sources(goroot, {'net/net_fake.go': FAKE_NETWORK_SHA256})['net/net_fake.go']
        adapted = closed_network_source(original)
        source = read_file(ROOT / FIXTURE / 'reference.go.txt')
        (output / 'main.go').write_bytes(source)
        (output / 'go.mod').write_bytes(b'module example.invalid/closed-network-reference\n\ngo 1.27.3\n')
        replacement = output / 'net_fake.go'
        replacement.write_text(adapted, encoding='utf-8', newline='\n')
        overlay = output / 'closed-overlay.json'
        overlay.write_bytes((json.dumps({'Replace': {str(goroot / 'src/net/net_fake.go'): str(replacement)}}) + '\n').encode())
        environment.update(GOTOOLCHAIN='local', GOWORK='off', GOENV='off', GOOS='wasip1', GOARCH='wasm',
                           CGO_ENABLED='0', GOPROXY='off', GOSUMDB='off', GOCACHE=str(output / 'cache'))
        modules, values = {}, {}
        for label in ('upstream', 'corrected'):
            module = output / (label + '.wasm')
            options = ('-overlay=' + str(overlay),) if label == 'corrected' else ()
            commands.run('compile-' + label, tools['go'], 'build', *options, '-o', module, 'main.go')
            modules[label] = file_identity(module, label + '.wasm', 16 * 1024 * 1024)
            values[label] = commands.run('execute-' + label, tools['node'],
                ROOT / FIXTURE / 'run-reference.mjs', module)
        measured = outcomes(values['upstream'], values['corrected'])
        if ({name: file_identity(path, name) for name, path in tools.items()} != before
                or checked_sources(goroot, {'net/net_fake.go': FAKE_NETWORK_SHA256})['net/net_fake.go'] != original
                or recipe != inventory({name: read_file(ROOT / name) for name in RECIPE})):
            raise ValueError('Go-closed-network-reference-input-changed')
        record.update(status='passed', outcomes=measured, modules=modules, sourceDigest=digest(source),
            upstreamDigest=digest(original.encode()), adaptedDigest=digest(adapted.encode()),
            stdoutDigests={name: digest(raw) for name, raw in values.items()})
        write_json(output / 'qualification.json', record)
        return record
    except BaseException:
        record['status'] = 'failed'
        write_json(output / 'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.output.resolve())))
