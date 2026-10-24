"""Actual CLR Task controls for the copied registry core, with explicit test ports."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment, file_identity
from tools.dotnet_guest import http_errors, managed_work
from tools.phase2_operator_process import require
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, inventory, read_file, snapshot, write_json

FIXTURE = 'sdk/dotnet-guest/tests/fixtures/managed-work-state-control'
SOURCES = (FIXTURE+'/Control.csproj', FIXTURE+'/Program.cs', FIXTURE+'/Bindings.cs',
    'sdk/dotnet-guest/tools/http-errors/ManagedWorkRuntime.cs',
    'sdk/dotnet-guest/tools/http-errors/ManagedWorkTimers.cs', 'sdk/dotnet-guest/global.json')
SETTLEMENT_CASES = (
    'enqueue-failure-settlement-refusal-retains-owner',
    'dequeue-settlement-refusal-retains-owner')
CASES = (
    'native-task-admission', 'unwrap-inner-actual-completion', 'queued-admission-rollback',
    'enqueue-failure-releases-both', 'continuation-failure-before-acceptance',
    'local-pop-releases-queue-only', 'join-real-required-task', 'callback-retains-async-void-task',
    'live-descendant-during-closing', 'closing-rejects-independent',
    'unobserved-original-fault-result', 'observed-fault-does-not-become-unhandled',
    'bounded-required-continuations', 'opaque-pending-is-not-quiescent',
    'untracked-startup-refused-before-admission', *SETTLEMENT_CASES)


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
        if name in SETTLEMENT_CASES:
            expected.update(settlementRefusals=1, retainedTasks=2, retainedQueuedOwners=1,
                            controlDispatches=0, automaticRetries=0, rootSuccess=False)
        require(len(raw) <= 1024 and json.loads(raw) == expected, 'managed-work-state-control-result')
        rows.append(expected)
    require(inventory(snapshot(source)) == before, 'managed-work-state-control-source-changed')
    value = {'profile': 'dotnet-managed-work-state-controls-v1', 'source': json.loads(before),
        'cases': rows, 'commands': commands.records, 'guestQualified': False,
        'productionContextDispatcherAndNativeLedgerQualified': False}
    write_json(output/'state-controls.json', value)
    return value


TIMER_CASES = (
    'native-storage-refusal-rolls-back-root', 'timer-admission-before-mutation-and-fresh',
    'change-reuses-original-owner', 'failed-change-rolls-back-unused-owner',
    'one-shot-delete-is-not-callback-return', 'multiple-queued-callbacks-retain-one-timer',
    'disposed-queued-callback-retires-after-cancelled-fire', 'callback-required-task-survives-return',
    'live-timer-descendant-during-closing', 'callback-throw-never-refunds-original-running-owner',
    'timer-structural-bound-before-ledger')

TIMER_WAIT_CASES = (
    'accepted_wait_can_start_after_closing_and_parent_return',
    'delayed_wait_outlives_its_creator_task',
    'dropping_before_first_poll_releases_the_original_wait',
    'invalid_constructor_parent_is_still_refused_without_leak',
    'invalid_explicit_wait_token_is_never_ambiently_replaced',
    'later_ambient_task_cannot_reparent_an_already_owned_wait')


def verify_timer_wait(output: Path) -> dict:
    """Compile the actual Rust Timer/Owner source with closed dependency ports."""
    output = fresh(Path(output).absolute())
    fixture = 'tools/fixtures/dotnet-timer-wait-control.rs'
    names = (fixture, 'sdk/dotnet-guest/runtime/http/owner.rs',
        'sdk/dotnet-guest/runtime/http/timer.rs')
    source = output/'source'
    for name in names:
        path = source/name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(read_file(ROOT/name))
    before = inventory(snapshot(source))
    environment = build_environment(output)
    environment.update(RUSTUP_TOOLCHAIN='1.97.1', RUSTUP_AUTO_INSTALL='0')
    commands = Commands(source, output, environment, deadline_seconds=120, command_seconds=60)
    rustc = shutil.which('rustc', path=commands.environment['PATH'])
    require(rustc is not None and commands.run('timer-wait-rustc-version', rustc, '--version').strip()
        == b'rustc 1.97.1 (8bab26f4f 2026-07-14)', 'timer-wait-source-control-rustc')
    executable = output/('timer-wait-control.exe' if sys.platform == 'win32' else 'timer-wait-control')
    commands.run('timer-wait-source-compile', rustc, '--edition=2021', '--test', source/fixture, '-o', executable)
    raw = commands.run('timer-wait-source-execute', executable, '--test-threads=1')
    require(len(raw) <= 16384 and b'test result: ok. 6 passed; 0 failed; 0 ignored;' in raw,
        'timer-wait-source-control-summary')
    rows = []
    for name in TIMER_WAIT_CASES:
        require(raw.count(('test '+name+' ... ok').encode('ascii')) == 1, 'timer-wait-source-control-case')
        rows.append({'control': name, 'passed': True, 'productionTimerOwnerSource': True,
            'ledgerClockPumpQuota': 'explicit-test-ports', 'guestQualified': False})
    require(inventory(snapshot(source)) == before, 'timer-wait-source-control-source-changed')
    value = {'profile': 'dotnet-deferred-timer-source-controls-v1', 'source': json.loads(before),
        'cases': rows, 'commands': commands.records, 'guestQualified': False,
        'actualHostClockAndNativeLedgerQualified': False}
    write_json(output/'timer-wait-source-controls.json', value)
    return value


def verify_timers(dotnet: Path, output: Path) -> dict:
    output = fresh(Path(output).absolute())
    fixture = 'sdk/dotnet-guest/tests/fixtures/managed-timer-state-control'
    names = (fixture+'/Control.csproj', fixture+'/Program.cs', fixture+'/Bindings.cs',
        'sdk/dotnet-guest/tools/http-errors/ManagedWorkRuntime.cs',
        'sdk/dotnet-guest/tools/http-errors/ManagedWorkTimers.cs', 'sdk/dotnet-guest/global.json')
    source = output/'source'
    for name in names:
        path = source/name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(read_file(ROOT/name))
    before = inventory(snapshot(source))
    config = source/'sdk/dotnet-guest/nuget.config'
    config.write_text('<configuration><packageSources><clear/></packageSources></configuration>', encoding='utf8')
    before = inventory(snapshot(source))
    project = source/fixture/'Control.csproj'
    commands = Commands(project.parent, output, build_environment(output), deadline_seconds=300, command_seconds=120)
    require(commands.run('timer-control-dotnet-version', dotnet, '--version').strip() == b'10.0.100',
        'managed-timer-state-control-sdk')
    commands.run('timer-control-build', dotnet, 'build', project, '-c', 'Release',
        '--output', output/'bin', '--artifacts-path', output/'artifacts',
        '-p:RestoreConfigFile='+str(config), '-p:NuGetAudit=false', '-nodeReuse:false')
    rows = []
    for name in TIMER_CASES:
        raw = commands.run('timer-control-'+name, dotnet, output/'bin/Control.dll', name)
        expected = {'control': name, 'passed': True, 'registryCore': 'production-source',
            'nativeLedger': 'explicit-test-port', 'timerProducerState': 'explicit-test-port',
            'actualClrTasks': True, 'guestQualified': False}
        require(len(raw) <= 1024 and json.loads(raw) == expected, 'managed-timer-state-control-result')
        rows.append(expected)
    require(inventory(snapshot(source)) == before, 'managed-timer-state-control-source-changed')
    value = {'profile': 'dotnet-managed-timer-state-controls-v1', 'source': json.loads(before),
        'cases': rows, 'commands': commands.records, 'guestQualified': False,
        'originalCoreLibProducerAndNativeLedgerQualified': False}
    write_json(output/'timer-state-controls.json', value)
    return value


def verify_timer_driver(dotnet: Path, tools: Path, output: Path) -> dict:
    """Execute the real selected driver CIL with explicit bounded queue ports."""
    from tools.dotnet_guest import task_wait
    output = fresh(Path(output).absolute())
    source = output/'source'; source.mkdir()
    fixture = 'tools/fixtures/dotnet-timer-driver-queue-control.cs'
    (source/'Program.cs').write_bytes(read_file(ROOT/fixture))
    (source/'global.json').write_bytes(read_file(ROOT/'sdk/dotnet-guest/global.json'))
    (source/'nuget.config').write_text('<configuration><packageSources><clear/></packageSources></configuration>', encoding='utf8')
    (source/'Control.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
        '<TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings>'
        '<Nullable>enable</Nullable><UseSharedCompilation>false</UseSharedCompilation><NuGetAudit>false</NuGetAudit>'
        '</PropertyGroup><ItemGroup><Reference Include="Mono.Cecil" HintPath="$(LsfCecilPath)" /></ItemGroup></Project>', encoding='utf8')
    before = inventory(snapshot(source))
    original = task_wait.source_path(tools/'packages')
    original_identity = task_wait.original(original)
    cecil = http_errors.cecil_path(tools)
    tool = http_errors.verify_installed(ROOT/'sdk/dotnet-guest', tools)
    commands = Commands(source, output, build_environment(output), deadline_seconds=300, command_seconds=120)
    require(commands.run('driver-control-dotnet-version', dotnet, '--version').strip() == b'10.0.100',
        'timer-driver-control-sdk')
    commands.run('driver-control-build', dotnet, 'build', source/'Control.csproj', '-c', 'Release',
        '--output', output/'bin', '--artifacts-path', output/'artifacts',
        '-p:LsfCecilPath='+str(cecil), '-nodeReuse:false')
    assembly = output/'derived-CoreLib.dll'
    commands.run('driver-control-current-normal-rewrite', dotnet, tools/'http-errors/HttpErrors.dll',
        '--managed-task-wait', original, assembly, output/'rewrite.json')
    rewrite = json.loads(read_file(output/'rewrite.json', http_errors.MAX_RECEIPT))
    task_wait.validate_receipt(rewrite, finite=True, managed=True)
    derived_identity = file_identity(assembly, 'driver-control-corelib', task_wait.MAX_ASSEMBLY)
    rows = []
    names = ['SetNextTimer', 'LsfTimerDriverToken', 'LsfTimerDriverRegister',
        'LsfTimerDriverCallback', 'LsfTimerDriverRetireIfIdle']
    for variant in ('old', 'new'):
        raw = commands.run('driver-control-copy-'+variant, dotnet, output/'bin/Control.dll',
            'graft', assembly, tools/'http-errors/HttpErrors.dll', output/variant, variant)
        require(len(raw) <= 1024 and json.loads(raw) == {'copiedActualDriverMethods': names,
            'testOnlyOriginalOptionProjection': variant == 'old', 'guestQualified': False}, 'timer-driver-closed-copy')
        for mode in (variant, 'success', 'fault'):
            raw = commands.run('driver-control-'+variant+'-'+mode, dotnet, output/variant/'Control.dll', 'execute', mode)
            require(len(raw) <= 2048, 'timer-driver-control-result-bound')
            value = json.loads(raw)
            if mode in ('old', 'new'):
                expected_trace = ['enqueued:1'] + (['enqueued:2', 'refused:2'] if mode == 'old' else ['enqueued:2'])
                expected_trace += ['dequeued:1', 'dequeued:0', 'enqueued:1', 'enqueued:2', 'refused:2',
                    'dequeued:1', 'enqueued:2', 'dequeued:1', 'dequeued:0']
                expected = {'passed': True, 'mode': mode, 'afterCancellation': 2 if mode == 'old' else 1,
                    'requiredContinuationRan': mode == 'new', 'actualQueuedCeiling': 2, 'maximumQueued': 2,
                    'originalCapacityRefusal': mode == 'old', 'threeRealEntriesStillRefused': True,
                    'freshSameBudget': True, 'guestQualified': False, 'queueAndNativeImports': 'explicit-test-ports',
                    'trace': expected_trace}
            else:
                expected = {'passed': True, 'mode': mode, 'originalCompletionPath': True,
                    'guestQualified': False, 'actualQueuedCeiling': 2}
            require(value == expected, 'timer-driver-exact-actual-clr-outcome')
            rows.append({'variant': variant, **value})
    require(inventory(snapshot(source)) == before and task_wait.original(original) == original_identity
        and file_identity(assembly, 'driver-control-corelib', task_wait.MAX_ASSEMBLY) == derived_identity
        and http_errors.verify_installed(ROOT/'sdk/dotnet-guest', tools) == tool,
        'timer-driver-control-original-source-tool-and-derived-unchanged')
    value = {'profile': 'dotnet-private-timer-driver-queue-controls-v1', 'cases': rows,
        'source': json.loads(before), 'original': original_identity, 'derived': derived_identity,
        'tool': tool, 'commands': commands.records, 'guestQualified': False,
        'queueAndNativeImports': 'explicit-test-ports'}
    write_json(output/'timer-driver-controls.json', value)
    return value


def verify_abort(dotnet: Path, tools: Path, output: Path) -> dict:
    """Run the real source-bound rewriter over exact original cleanup bodies."""
    output = fresh(Path(output).absolute())
    fixture = 'sdk/dotnet-guest/tests/fixtures/http-abort-control'
    names = (fixture+'/Control.csproj', fixture+'/Program.cs', 'sdk/dotnet-guest/global.json',
        *('sdk/dotnet-guest/tools/http-errors/'+name for name in (
            'Program.cs', 'TaskWait.cs', 'IdleTimerDriver.cs', 'ClosedFilesystem.cs',
            'ManagedWorkRuntime.cs', 'ManagedWorkTimers.cs', 'ManagedWorkBindings.cs', 'ManagedWorkCopy.cs',
            'ManagedWorkContext.cs', 'ManagedWorkHooks.cs', 'ManagedWorkPort.cs', 'ManagedHttpWork.cs')))
    source = output/'source'
    for name in names:
        path = source/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(read_file(ROOT/name))
    before = inventory(snapshot(source))
    original = http_errors.source_paths(tools)[0]
    original_identity = http_errors.require_digest(original, http_errors.SOURCE_DIGEST, 'abort-control-original')
    cecil = http_errors.cecil_path(tools)
    cecil_identity = http_errors.require_digest(cecil, http_errors.CECIL_DIGEST, 'abort-control-cecil')
    tool_identity = http_errors.verify_installed(ROOT/'sdk/dotnet-guest', tools)
    config = output/'nuget.config'
    config.write_text('<configuration><packageSources><clear/></packageSources></configuration>', encoding='utf8')
    project = source/fixture/'Control.csproj'
    commands = Commands(project.parent, output, build_environment(output), deadline_seconds=300, command_seconds=120)
    require(commands.run('abort-control-dotnet-version', dotnet, '--version').strip() == b'10.0.100',
        'http-abort-control-sdk')
    commands.run('abort-control-build', dotnet, 'build', project, '-c', 'Release',
        '--output', output/'bin', '--artifacts-path', output/'artifacts',
        '-p:RestoreConfigFile='+str(config), '-p:LsfCecilPath='+str(cecil), '-p:NuGetAudit=false', '-nodeReuse:false')
    rows = []
    for mode, corrected in (('old', False), ('new', True)):
        raw = commands.run('abort-control-derive-'+mode, dotnet, output/'bin/Control.dll',
            'derive', original, output/mode, mode)
        value = json.loads(raw)
        expected = {'sourceHttp': http_errors.SOURCE_DIGEST.removeprefix('sha256:'),
            'copiedActualBodies': 3, 'corrected': corrected,
            'copiedGeneratedHelpers': 1 if corrected else 0,
            'assembly': file_identity(output/mode/'Control.dll', 'control', 2*1024*1024)['digest'].removeprefix('sha256:'),
            'guestQualified': False}
        require(len(raw) <= 1024 and value == expected, 'http-abort-control-derive')
        raw = commands.run('abort-control-execute-'+mode, dotnet, output/mode/'Control.dll', 'execute', mode)
        expected = {'corrected': corrected, 'copiedActualBodies': 3,
            'originalExceptionPreserved': corrected,
            'failedEvents': ['stream-drop', 'body-abort', 'input-drop', 'future-drop'] if corrected
                else ['stream-drop', 'body-finish'],
            'successEvents': ['stream-drop', 'body-finish'],
            'nativeResources': 'explicit-test-ports', 'guestQualified': False}
        require(len(raw) <= 1024 and json.loads(raw) == expected, 'http-abort-control-execute')
        rows.append(expected)
    commands.run('abort-control-full-rewrite', dotnet, tools/'http-errors/HttpErrors.dll', '--managed-sync-read',
        original, output/'System.Net.Http.dll', output/'rewrite.json')
    rewrite = json.loads(read_file(output/'rewrite.json', http_errors.MAX_RECEIPT))
    managed_work.validate_http_rewrite(rewrite['requiredContentWork'])
    managed_work.validate_abort_rewrite(rewrite['requestAbortCleanup'])
    require(inventory(snapshot(source)) == before, 'http-abort-control-source-changed')
    require(http_errors.require_digest(original, http_errors.SOURCE_DIGEST, 'abort-control-original') == original_identity
        and http_errors.require_digest(cecil, http_errors.CECIL_DIGEST, 'abort-control-cecil') == cecil_identity,
        'http-abort-control-original-changed')
    require(http_errors.verify_installed(ROOT/'sdk/dotnet-guest', tools) == tool_identity,
        'http-abort-control-rewriter-changed')
    value = {'profile': 'dotnet-http-abort-cleanup-controls-v1', 'source': json.loads(before),
        'original': original_identity, 'cecil': cecil_identity, 'cases': rows, 'rewrite': rewrite,
        'commands': commands.records, 'guestQualified': False}
    write_json(output/'abort-controls.json', value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dotnet', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--http-abort-tools', type=Path)
    modes.add_argument('--timers', action='store_true')
    modes.add_argument('--timer-wait-source', action='store_true')
    modes.add_argument('--timer-driver-tools', type=Path)
    args = parser.parse_args()
    value = (verify_timer_driver(args.dotnet.resolve(strict=True), args.timer_driver_tools.resolve(strict=True), args.output)
        if args.timer_driver_tools is not None else verify_timer_wait(args.output) if args.timer_wait_source else
        verify_abort(args.dotnet.resolve(strict=True), args.http_abort_tools.resolve(strict=True), args.output)
        if args.http_abort_tools is not None else verify_timers(args.dotnet.resolve(strict=True), args.output)
        if args.timers else verify(args.dotnet.resolve(strict=True), args.output))
    print(json.dumps({'cases': len(value['cases']), 'guestQualified': False}))


if __name__ == '__main__':
    main()
