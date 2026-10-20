#!/usr/bin/env python3
"""Execute the private owner reference and construct one real Go net component.

No signing, host/provider installation or TCP/kernel/TLS execution is performed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.go_capsule_build import RECIPE as BUILD_RECIPE
from tools.go_guest.activation import MANAGED_PROFILE
from tools.go_guest.compiler import Compiler
from tools.build_observation import file_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, snapshot, write_json
from tools.stage_runtime_wit import stage

OWNER_TEST = 'tools/tests/fixtures/go_network/connection-owner-test.go.txt'
OWNER_CASES = (
    'TestIndependentReadWriteAndSameDirectionRefusal',
    'TestCloseCancelsBothDirectionsButWaitsForRealAcknowledgements',
    'TestSendShutdownSharesWriteOwnerAndPreservesRead',
    'TestCloseWithoutBorrowRetainsOneFinalOwner',
    'TestInvalidOwnerDirectionOrContextNeverBorrows',
    'TestDuplicateReleaseFailsClosedWithoutRefundingAnotherDirection',
)
RECIPE = (*BUILD_RECIPE, 'tools/qualify_go_network_compile.py', OWNER_TEST)


def owner_result(raw: bytes) -> list[str]:
    if len(raw) > 262144:
        raise ValueError('Go-network-owner-output-bound')
    if not raw.strip():
        raise ValueError('Go-network-owner-result-incomplete')
    passed = []
    package_passed = False
    for line in raw.splitlines():
        row = json.loads(line)
        if not isinstance(row, dict) or row.get('Package') != 'example.invalid/stream-owner':
            raise ValueError('Go-network-owner-result-package')
        action, case = row.get('Action'), row.get('Test')
        if action not in {'start', 'run', 'output', 'pass'} or case is not None and case not in OWNER_CASES:
            raise ValueError('Go-network-owner-result-failed-or-unknown')
        if action == 'pass' and case is not None:
            if case in passed:
                raise ValueError('Go-network-owner-result-duplicate')
            passed.append(case)
        elif action == 'pass' and case is None:
            if package_passed:
                raise ValueError('Go-network-owner-result-duplicate-package')
            package_passed = True
    if set(passed) != set(OWNER_CASES) or not package_passed:
        raise ValueError('Go-network-owner-result-incomplete')
    return passed


def qualify(output: Path) -> dict:
    output = fresh(output)
    fixture = ROOT / 'sdk/go-guest/runtime/network-conformance'
    source = snapshot(fixture)
    sdk_before = inventory(snapshot(ROOT / 'sdk/go-guest'))
    recipe_before = inventory({name: read_file(ROOT / name) for name in RECIPE})
    record = {'schemaVersion': 'latent.go.network.compile.v1', 'status': 'in-progress',
        'profile': MANAGED_PROFILE, 'qualification': 'construction-and-private-owner-reference-only',
        'signedExecution': 'not-run', 'providerInstalled': False, 'kernelAccountingQualified': False,
        'sourceDigest': digest(inventory(source)), 'sdkDigest': digest(sdk_before),
        'recipeDigest': digest(recipe_before),
        'commandLimits': {'overallSeconds': 900, 'perCommandSeconds': 600}}
    (output / 'source-inputs.json').write_bytes(inventory(source))
    (output / 'recipe-inputs.json').write_bytes(recipe_before)
    commands = Commands(output, output, dict(os.environ), deadline_seconds=900, command_seconds=600)
    try:
        go_path = shutil.which('go', path=commands.environment['PATH'])
        if go_path is None:
            raise ValueError('Go-network-reference-compiler-unavailable')
        go_path = Path(go_path).resolve(strict=True)
        reference_tool = file_identity(go_path, 'go')
        if commands.run('reference-go-version', go_path, 'version').split() != [b'go', b'version', b'go1.27.2', b'linux/amd64']:
            raise ValueError('Go-network-reference-compiler-identity')
        # This standalone reference compiles only the exact private owner source
        # against ordinary Go context/sync. It has no WIT/native host substitute.
        owner = output / 'owner-reference'
        owner.mkdir()
        (owner / 'go.mod').write_bytes(b'module example.invalid/stream-owner\n\ngo 1.27.2\n')
        owner_source = read_file(ROOT / 'sdk/go-guest/capabilities/network-owner.go.in')
        owner_tests = read_file(ROOT / OWNER_TEST)
        (owner / 'owner.go').write_bytes(owner_source)
        (owner / 'owner_test.go').write_bytes(owner_tests)
        original_root = commands.root
        original_environment = commands.environment
        try:
            commands.root = owner
            commands.environment = dict(original_environment, GOTOOLCHAIN='local', GOWORK='off', GOENV='off',
                GOOS='linux', GOARCH='amd64', CGO_ENABLED='0', GOPROXY='off', GOSUMDB='off',
                GOCACHE=str(output / 'owner-cache'))
            raw = commands.run('actual-private-owner-reference', go_path, 'test', '-json', '-timeout=10s', '-count=1', './...')
        finally:
            commands.root = original_root
            commands.environment = original_environment
        if file_identity(go_path, 'go') != reference_tool:
            raise ValueError('Go-network-reference-compiler-changed')
        record['ownerReference'] = {'cases': owner_result(raw), 'sourceDigest': digest(owner_source),
            'testsDigest': digest(owner_tests), 'stdoutDigest': digest(raw), 'compiler': reference_tool,
            'hostIoExecution': False}
        (output / 'src').mkdir()
        (output / 'src/main.go').write_bytes(source['main.go'])
        for name in ('go.mod', 'go.sum'):
            (output / name).write_bytes(read_file(ROOT / 'sdk/go-guest/runtime-deps' / name))
        stage(output / 'wit', fixture)
        compiler = Compiler(output / 'compiler', ROOT / 'sdk/go-guest', commands, runtime_profile=MANAGED_PROFILE)
        component, bindings = compiler.compile(output / 'src', output / 'wit',
            'examples:go-standard-network/service@1.0.0', output / 'build', runtime_profile=MANAGED_PROFILE)
        compiler.check_unchanged()
        surface = read_file(output / 'build/component.wit').decode('utf-8')
        if 'latent:network/streams@0.1.0' not in surface:
            raise ValueError('Go-network-component-lost-declared-import')
        if (source != snapshot(fixture) or sdk_before != inventory(snapshot(ROOT / 'sdk/go-guest'))
                or recipe_before != inventory({name: read_file(ROOT / name) for name in RECIPE})):
            raise ValueError('Go-network-captured-source-changed')
        record.update(status='passed', componentDigest=digest(read_file(component, 64 * 1024 * 1024)),
            bindingDigest=digest(json.dumps(bindings, sort_keys=True).encode()), tools=compiler.materials)
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
