"""Actual CLR Task controls for the copied registry core, with explicit test ports."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.phase2_operator_process import require
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, inventory, read_file, snapshot, write_json

FIXTURE = 'sdk/dotnet-guest/tests/fixtures/managed-work-state-control'
SOURCES = (FIXTURE+'/Control.csproj', FIXTURE+'/Program.cs', FIXTURE+'/Bindings.cs',
    'sdk/dotnet-guest/tools/http-errors/ManagedWorkRuntime.cs', 'sdk/dotnet-guest/global.json')
CASES = (
    'native-task-admission', 'unwrap-inner-actual-completion', 'queued-admission-rollback',
    'enqueue-failure-releases-both', 'continuation-failure-before-acceptance',
    'local-pop-releases-queue-only', 'join-real-required-task', 'callback-retains-async-void-task',
    'live-descendant-during-closing', 'closing-rejects-independent',
    'unobserved-original-fault-result', 'observed-fault-does-not-become-unhandled',
    'bounded-required-continuations', 'opaque-pending-is-not-quiescent',
    'untracked-startup-refused-before-admission')


def verify(dotnet: Path, output: Path) -> dict:
    output = fresh(Path(output).absolute())
    source = output/'source'
    for name in SOURCES:
        path = source/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(read_file(ROOT/name))
    config = source/'sdk/dotnet-guest/nuget.config'
    config.write_text('<configuration><packageSources><clear/></packageSources></configuration>', encoding='utf8')
    before = inventory(snapshot(source))
    project = source/FIXTURE/'Control.csproj'
    commands = Commands(project.parent, output, build_environment(output), deadline_seconds=300, command_seconds=120)
    require(commands.run('state-control-dotnet-version', dotnet, '--version').strip() == b'10.0.100',
        'managed-work-state-control-sdk')
    commands.run('state-control-build', dotnet, 'build', project, '-c', 'Release',
        '--output', output/'bin', '--artifacts-path', output/'artifacts',
        '-p:RestoreConfigFile='+str(config), '-p:NuGetAudit=false', '-nodeReuse:false')
    rows = []
    for name in CASES:
        raw = commands.run('state-control-'+name, dotnet, output/'bin/Control.dll', name)
        expected = {'control': name, 'passed': True, 'registryCore': 'production-source',
            'nativeLedger': 'explicit-test-port', 'dispatcher': 'explicit-test-port',
            'actualClrTasks': True, 'guestQualified': False}
        require(len(raw) <= 1024 and json.loads(raw) == expected, 'managed-work-state-control-result')
        rows.append(expected)
    require(inventory(snapshot(source)) == before, 'managed-work-state-control-source-changed')
    value = {'profile': 'dotnet-managed-work-state-controls-v1', 'source': json.loads(before),
        'cases': rows, 'commands': commands.records, 'guestQualified': False,
        'productionContextDispatcherAndNativeLedgerQualified': False}
    write_json(output/'state-controls.json', value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dotnet', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    value = verify(args.dotnet.resolve(strict=True), args.output)
    print(json.dumps({'cases': len(value['cases']), 'guestQualified': False}))


if __name__ == '__main__':
    main()
