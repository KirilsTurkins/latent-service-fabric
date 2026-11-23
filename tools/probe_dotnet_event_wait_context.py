#!/usr/bin/env python3
"""Run the pinned emitted wait helpers on CLR; never claim signed WASI qualification."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.dotnet_guest import http_errors, task_wait
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, snapshot, write_json

MARKERS = (
    'FINITE_WAIT_EMITTED_IL_HOST PASS ',
    'AGGREGATE_FINITE_IL_HOST PASS ',
    'MANUAL_RESET_EVENT_IL_HOST PASS ',
)


def copy_sources(source: Path, destination: Path) -> dict[str, bytes]:
    files = snapshot(source)
    destination.mkdir()
    for name, data in files.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return files


def probe(output: Path) -> dict:
    output = fresh(output)
    sdk = ROOT / 'sdk/dotnet-guest'
    stage = 'source-capture'
    commands = None
    try:
        # Restore the existing reviewed SDK graph in a private directory. No
        # native compiler, WASI adapter, service, signing key or grant is used.
        inputs = {}
        for source, name in (('global.json', 'global.json'), ('nuget.config', 'nuget.config'),
                             ('probes/smoke/Smoke.csproj', 'Smoke.csproj'),
                             ('probes/smoke/packages.lock.json', 'packages.lock.json')):
            data = read_file(sdk / source)
            inputs[source] = data
            (output / name).write_bytes(data)
        environment = build_environment(output)
        environment.update(DOTNET_CLI_HOME=str(output / 'cli-home'), DOTNET_ROLL_FORWARD='Disable',
            DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1',
            DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE='true', MSBUILDDISABLENODEREUSE='1',
            DOTNET_CLI_USE_MSBUILD_SERVER='0', NUGET_PACKAGES=str(output / 'packages'))
        commands = Commands(output, output, environment, deadline_seconds=600, command_seconds=180)
        dotnet = shutil.which('dotnet', path=environment['PATH'])
        stage = 'sdk-version'
        if not dotnet or commands.run(stage, dotnet, '--version').strip() != b'10.0.100':
            raise ValueError('event-context-pinned-sdk-required')
        stage = 'locked-restore'
        commands.run(stage, dotnet, 'restore', output / 'Smoke.csproj', '--configfile', output / 'nuget.config',
            '--locked-mode', '--packages', output / 'packages', '--disable-parallel', '-p:NuGetAudit=false',
            '-p:ImportDirectoryBuildProps=false', '-p:ImportDirectoryBuildTargets=false')
        if read_file(output / 'packages.lock.json') != inputs['probes/smoke/packages.lock.json']:
            raise ValueError('event-context-lock-changed')
        stage = 'rewriter-build'
        http_errors.install(sdk, output, Path(dotnet), commands.run)
        original = task_wait.source_path(output / 'packages')
        original_identity = task_wait.original(original)
        rewriter = output / 'http-errors/HttpErrors.dll'
        cecil = output / 'http-errors/Mono.Cecil.dll'
        receipts = {}
        receipt_failures = []
        for name, option, finite, managed, aggregate in (
                ('infinite', '--task-wait', False, False, False),
                ('finite', '--finite-task-wait', True, False, False),
                ('aggregate', '--aggregate-task-wait', True, True, True)):
            stage = name + '-rewrite'
            commands.run(stage, dotnet, rewriter, option, original, output / (name + '.dll'),
                         output / (name + '.json'))
            receipt = json.loads(read_file(output / (name + '.json'), http_errors.MAX_RECEIPT))
            # Collect independent receipt and behavioral diagnostics, but never
            # issue HOST-COMPLETE when either gate rejects the candidate.
            try:
                task_wait.validate_current_receipt(receipt, finite=finite, managed=managed, aggregate=aggregate,
                                                   require_finite_observation=finite)
            except ValueError:
                receipt_failures.append(name)
            if receipt['outputDigest'] != digest(read_file(output / (name + '.dll'), task_wait.MAX_ASSEMBLY)):
                raise ValueError('event-context-derived-digest')
            receipts[name] = receipt
        write_json(output / 'receipt-validation.json', {'rejected': receipt_failures})
        stage = 'projection-build'
        fixture = sdk / 'tests/fixtures/task-wait-finite-il-control'
        source = output / 'control-source'
        fixture_inputs = copy_sources(fixture, source)
        (source / 'nuget.config').write_text(
            '<configuration><packageSources><clear /></packageSources></configuration>\n', encoding='utf-8')
        commands.run(stage, dotnet, 'build', source / 'FiniteIlControl.csproj', '-c', 'Release',
            '--output', output / 'control', '--artifacts-path', output / 'control-artifacts',
            '-p:LsfCecilPath=' + str(cecil), '-p:RestoreConfigFile=' + str(source / 'nuget.config'),
            '-p:NuGetAudit=false', '-p:UseSharedCompilation=false', '-nodeReuse:false',
            '-p:ImportDirectoryBuildProps=false', '-p:ImportDirectoryBuildTargets=false')
        stage = 'emitted-host-projection'
        observed = commands.run(stage, dotnet, output / 'control/FiniteIlControl.dll', output / 'infinite.dll',
            output / 'finite.dll', rewriter, output / 'projection.dll', output / 'aggregate.dll')
        lines = observed.decode('utf-8').splitlines()
        if any(sum(line.startswith(marker) for line in lines) != 1 for marker in MARKERS):
            raise ValueError('event-context-host-completion-missing')
        stage = 'receipt-validation'
        if receipt_failures:
            raise ValueError('event-context-current-receipt-rejected')
        stage = 'input-recheck'
        if (task_wait.original(original) != original_identity or snapshot(fixture) != fixture_inputs
                or any(read_file(sdk / path) != data for path, data in inputs.items())):
            raise ValueError('event-context-inputs-changed')
        http_errors.verify_installed(sdk, output)
        result = {'schemaVersion': 'latent.dotnet.event-wait-host.v1', 'status': 'passed',
            'scope': 'CLR-reference-and-emitted-helper-host-projection', 'signedWasiQualified': False,
            'nativeAotQualified': False, 'original': original_identity,
            'fixtureSourceDigest': digest(inventory(fixture_inputs)),
            'aggregateReceipt': receipts['aggregate']['aggregateTaskWait'], 'commands': commands.records}
        write_json(output / 'HOST-COMPLETE.json', result)
        return result
    except BaseException as error:
        write_json(output / 'HOST-FAILED.json', {'schemaVersion': 'latent.dotnet.event-wait-host.v1',
            'status': 'failed', 'stage': stage, 'reason': type(error).__name__,
            'signedWasiQualified': False, 'nativeAotQualified': False,
            'commands': commands.records if commands is not None else []})
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = probe(args.output)
    except (ValueError, RuntimeError, OSError):
        print('event-wait-context-host-failed; inspect bounded stage logs', file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
