"""Replay one immutable C component with a numeric, nonqualifying test host.

The ordinary signed C node owner and its existing assertions remain in charge.
The host has a dedicated observation feature; no guest is rebuilt or edited.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import time
from unittest.mock import patch
import zipfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import c_timed_runtime_node as node
from tools.build_observation import build_environment
from tools.phase2_operator_process import WorkflowError, require, write_json
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, read_file

ORIGINAL = {
    'run': 42525327883, 'job': 128867585737, 'artifact': 13638659294,
    'sourceCommit': '14a55263ca17359603df3691f20a1dcac25ca17e',
    'archiveBytes': 2280201,
    'archiveSha256': '4f28a85e0308d829af4ae5b8680dd947e5320f6b5987f8cac43fe11e01029e37',
    'members': 555, 'expandedBytes': 8294131,
}
COMPONENT = 'sha256:c9d0fba3a01d8784e9bd7ef23e03a2ab85921622ebecef592673eaf44335e205'
PREFIX = b'LSF_C_TIMED_ORIGINAL_TRAP '
BUDGET = {'blobReadBytes': 0, 'blobWriteBytes': 0, 'childCalls': 0, 'cpuFuel': 1_000_000_000,
          'effectCount': 0, 'logBytes': 0, 'memoryBytes': 33_554_432, 'outboundRequests': 0,
          'stateReadBytes': 0, 'stateWriteBytes': 0, 'wallTimeLimitMillis': 5000}
LIMITS = {'tasks': 8, 'executors': 2, 'queuedWork': 8, 'waits': 16, 'timers': 8,
          'results': 8, 'nativeOwners': 8}
INPUTS = {
    'BUILD-COMPLETE.json': (2875, '5dbd0a475158fc14349884e2c1910069194e4a7f623cd4221f24d8263d49649f'),
    'build-observation.json': (7124, '192e870bf946113b6e85f853a61ea5bd49fa85f5abaee375a6184de526e630a6'),
    'c-threading-compatibility.json': (1731, '36e5623f80391e59a1ba9b710309c1a1846e782cca6a4bc2736bc7ffb1fc7f96'),
    'capsule.json': (1495, 'da72226ff10958b618c7c440fe547b2f0bd14f95512962074a1da9c22a0b8517'),
    'compatibility-inspection.json': (756, '8bd42501ba84c26d980d543eb36d929f4601d6e5012595069760a1c4ebdb874a'),
    'compatibility-report.json': (1418, '9e350a2667d34b47cfedbc19abfdb9a76b571c4461af7a192fc0062689e63b55'),
    'component.wasm': (2094701, 'c9d0fba3a01d8784e9bd7ef23e03a2ab85921622ebecef592673eaf44335e205'),
    'contracts.json': (697, 'cbcae3c3f4b264fee0fbfecf0314d2b07a9e9f714fcacf405d3311e04c19ac89'),
    'deployment.json': (893, 'cfcbfed8acaf17fb5c103826f195e18cae95ec89e7d625318631d18af30aa623'),
    'package-inputs.json': (1594, '61e1bffdbaec7eb196580cc9a174d9c4b5459f3ae02c85195f7725fc29b0e913'),
    'package-source.json': (2258, 'babf93e9e1fb99d3d971024809660b725c1848ef95cbfbb87c50872da5cc5526'),
    'source-inputs.json': (10511, 'f99cd66143b5c24c01a1a38f43bb6d80230dc0df92418d48ead2af5035ac82d2'),
    'wit-lock.json': (1181, 'dac415de65e006d164098baab60a4f28060cd31882268b782e5492d418e18d5d'),
    'wit/deps/activation-runtime/package.wit': (2539, '0855e3524edbe15a5d174a825df6034ef41cd87f1330e2fba884ea6e2c58e946'),
    'wit/deps/clock/package.wit': (139, 'a009ecd4ad23d581523fe97b66327ebe352ac27c9c72d4e09ecc9bb003c466ea'),
    'wit/deps/native-runtime/package.wit': (633, '2433ec06c033be01474fd5bf3275c921622eb6720aac344f1307736d09325eb6'),
    'wit/deps/random/package.wit': (272, 'c8ceca00269182f27c785fe17bd42eb4776bcde96828e5b5f2786aa15dbedc60'),
    'wit/world.wit': (359, '3a66bb0285f2149a167378789f1c8f628707d4620668dabfa10eb8dcc8a7bc5e'),
}


def identity(raw):
    return {'bytes': len(raw), 'sha256': 'sha256:' + hashlib.sha256(raw).hexdigest()}


def decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'c-timed-original-duplicate-json-field')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def restore(raw, destination, deadline):
    require(type(raw) is bytes and len(raw) == ORIGINAL['archiveBytes']
            and hashlib.sha256(raw).hexdigest() == ORIGINAL['archiveSha256'],
            'c-timed-original-archive-identity')
    payloads, seen, total = {}, set(), 0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        require(len(entries) == ORIGINAL['members'], 'c-timed-original-member-count')
        for entry in entries:
            name = entry.filename
            path, key = PurePosixPath(name), name.casefold()
            require(time.monotonic() < deadline and name and len(name.encode()) <= 512
                    and path.as_posix() == name and not path.is_absolute()
                    and not any(part in ('', '.', '..') for part in path.parts)
                    and '\\' not in name and ':' not in name and not entry.is_dir()
                    and stat.S_IFMT(entry.external_attr >> 16) in (0, stat.S_IFREG)
                    and not entry.flag_bits & 1 and entry.compress_type == 8
                    and key not in seen and not any(key.startswith(x + '/') or x.startswith(key + '/') for x in seen),
                    'c-timed-original-regular-member')
            seen.add(key)
            total += entry.file_size
            require(0 <= entry.file_size <= 4 * 1024**2 and total <= 9 * 1024**2,
                    'c-timed-original-expanded-bound')
        require(total == ORIGINAL['expandedBytes'], 'c-timed-original-expanded-size')
        for name, (size, digest) in INPUTS.items():
            data = archive.read('c-thread-runtime/build/' + name)
            require(identity(data) == {'bytes': size, 'sha256': 'sha256:' + digest},
                    'c-timed-original-package-input')
            payloads[name] = data
        historical = decode(archive.read('c-thread-runtime/node/invocation-c-thread-timed-sleep.json'))
    response = historical['response']
    require(historical['activation'] == 'c-thread-timed-sleep' and historical['exitCode'] == 4
            and historical['processReaped'] is True and historical['decoded'] is None
            and response['outcomeKnown'] is True and response['requestDispatched'] is True
            and response['error']['code'] == 'guest-trap'
            and response['data']['terminalState'] == 'guest_trap'
            and response['data']['resolvedRevision']['releaseDigest'] == COMPONENT,
            'c-timed-original-historical-failure')
    marker = decode(payloads['BUILD-COMPLETE.json'])
    observed = decode(payloads['build-observation.json'])
    inventory = decode(payloads['package-inputs.json'])
    require(marker['packageAssembled'] is True and marker['componentDigest'] == COMPONENT
            and marker['sourceDigest'] == identity(payloads['source-inputs.json'])['sha256']
            and marker['observationDigest'] == identity(payloads['build-observation.json'])['sha256']
            and observed['componentDigest'] == COMPONENT and observed['componentSize'] == INPUTS['component.wasm'][0],
            'c-timed-original-build-binding')
    require(len(inventory) == 13 and set(inventory) <= set(payloads)
            and all(inventory[name] == {'digest': identity(payloads[name])['sha256'], 'size': len(payloads[name])}
                    for name in inventory), 'c-timed-original-package-inventory')
    destination = fresh(destination)
    for name, data in payloads.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as sink:
            sink.write(data)
    return {'origin': ORIGINAL, 'component': COMPONENT, 'packageInputs': len(inventory),
            'sourceAndObservationBound': True, 'historicalExitCode': 4,
            'historicalTrap': 'guest-trap', 'historicalBacktraceRetained': False}


def numeric_event(stderr):
    require(type(stderr) is bytes and len(stderr) <= 262144, 'c-timed-observer-stderr-bound')
    lines = [line for line in stderr.splitlines() if line.startswith(PREFIX)]
    require(len(lines) == 1 and len(lines[0]) <= 4096, 'c-timed-observer-event-count')
    row = decode(lines[0][len(PREFIX):])
    fields = {'observedErrors', 'ambiguous', 'trapKind', 'missingBacktrace',
              'mayBeTruncated', 'observedFrames', 'engineFrameCap', 'frames'}
    require(type(row) is dict and set(row) == fields and type(row['observedErrors']) is int
            and row['observedErrors'] in (0, 1) and row['ambiguous'] is False
            and type(row['missingBacktrace']) is bool and type(row['mayBeTruncated']) is bool
            and type(row['observedFrames']) is int and 0 <= row['observedFrames'] <= 16
            and type(row['frames']) is list and len(row['frames']) == 16,
            'c-timed-observer-closed-snapshot')
    if row['observedErrors'] == 0:
        require(row['trapKind'] is None and row['engineFrameCap'] is None
                and row['observedFrames'] == 0 and row['missingBacktrace'] is False
                and row['mayBeTruncated'] is False, 'c-timed-observer-empty-snapshot')
    else:
        trap_kinds = (None, 'stack-overflow', 'memory-out-of-bounds', 'heap-misaligned',
                      'table-out-of-bounds', 'indirect-call-to-null', 'bad-signature',
                      'integer-overflow', 'integer-division-by-zero', 'bad-conversion-to-integer',
                      'unreachable-code', 'allocation-too-large', 'cannot-block-sync-task',
                      'cannot-resume-thread', 'guest-fault')
        require(row['trapKind'] in trap_kinds and row['engineFrameCap'] == 16
                and row['mayBeTruncated'] is (row['observedFrames'] >= 16),
                'c-timed-observer-trap-snapshot')
    modules = set()
    for index, frame in enumerate(row['frames']):
        if index >= row['observedFrames']:
            require(frame is None, 'c-timed-observer-frame-tail')
            continue
        require(type(frame) is dict and set(frame) == {'module', 'function', 'moduleOffset', 'functionOffset'}
                and type(frame['module']) is int and 0 <= frame['module'] <= len(modules) < 16
                and type(frame['function']) is int and 0 <= frame['function'] < 2**32
                and all(frame[k] is None or type(frame[k]) is int and 0 <= frame[k] < 2**32
                        for k in ('moduleOffset', 'functionOffset')), 'c-timed-observer-frame')
        modules.add(frame['module'])
    return row


class TargetCompleted(Exception):
    """The target passed its original assertions; do not run later cases."""


def replay(artifact, native, output):
    captured = {'targetAttempted': False, 'configurationChecked': False, 'event': None, 'eventFailure': None}
    original_programme, original_invoke = node.programme, node.invoke_timed
    original_configure, original_connect = node.configure, node.connect

    def connect(client, *args, **kwargs):
        # The maintained client normally supplies a clean, fixed environment.
        # Add this one diagnostic-only opt-in solely while spawning its node.
        key = 'LSF_C_TIMED_ORIGINAL_TRAP'
        require(key not in client.environment, 'c-timed-diagnostic-env-already-set')
        client.environment[key] = '1'
        try:
            return original_connect(client, *args, **kwargs)
        finally:
            del client.environment[key]

    def configure(settings, capsule):
        result = original_configure(settings, capsule)
        runtime = settings['providers']['activationRuntime']
        require(settings['engine'] == {'threadingProfile': 'c-context144-sync-cooperative-v1'}
                and runtime['limits'] == LIMITS and runtime['nativeThreads'] is True
                and settings['workers'] == {'runtime': 1, 'control': 1}
                and settings['cells'] == [{'class': 'standard', 'capacity': 1,
                    'queueCapacity': 2, 'maximumMemoryBytes': 67_108_864}],
                'c-timed-original-profile-and-limits')
        captured['configurationChecked'] = True
        return result

    def programme(client, process, probe, manifest, target, result_output):
        require(captured['configurationChecked'] and target['budget'] == BUDGET,
                'c-timed-original-activation-budget')
        def invoke(client, probe, target, output, mode, activation):
            if mode != 'timed-sleep' or activation != 'c-thread-timed-sleep':
                return original_invoke(client, probe, target, output, mode, activation)
            captured['targetAttempted'] = True
            try:
                original_invoke(client, probe, target, output, mode, activation)
                raise TargetCompleted()
            finally:
                try:
                    for _ in range(4):
                        process.drain()
                    captured['event'] = numeric_event(bytes(process.buffers[1]))
                except Exception as error:
                    captured['eventFailure'] = type(error).__name__
        with patch.object(node, 'invoke_timed', invoke):
            return original_programme(client, process, probe, manifest, target, result_output)

    with patch.object(node, 'programme', programme), patch.object(node, 'configure', configure), \
            patch.object(node, 'connect', connect):
        try:
            node.run(artifact, native, output)
            raise WorkflowError('c-timed-target-not-intercepted')
        except TargetCompleted:
            status = 'target-completed'
        except WorkflowError as error:
            if str(error) != 'c-timed-ordinary-success' or not captured['targetAttempted']:
                raise
            status = 'target-original-success-assertion-failed'
    require(captured['targetAttempted'] and captured['event'] is not None
            and captured['eventFailure'] is None, 'c-timed-target-observation-unavailable')
    owner = decode(read_file(output / 'FAILED.json', 262144))
    require(owner['status'] == 'failed' and owner['stage'] == 'ordinary-c-thread-lifecycle'
            and owner.get('cleanupRefused') is not True, 'c-timed-original-owner-cleanup')
    row = decode(read_file(output / 'invocation-c-thread-timed-sleep.json', 262144))
    data = row['response']['data']
    require(row['activation'] == 'c-thread-timed-sleep' and row['processReaped'] is True
            and row['response']['outcomeKnown'] is True and row['response']['requestDispatched'] is True
            and data['resolvedRevision']['releaseDigest'] == COMPONENT,
            'c-timed-target-replay-association')
    if status == 'target-original-success-assertion-failed':
        require(row['exitCode'] == 4 and row['response']['error']['code'] == 'guest-trap'
                and data['terminalState'] == 'guest_trap' and captured['event']['observedErrors'] == 1,
                'c-timed-target-replay-trap')
        details = row['response']['error'].get('details', [])
        kinds = [item.get('fields', {}).get('kind') for item in details
                 if isinstance(item, dict) and item.get('kind') == 'activation.guest-trap-kind']
        if captured['event']['trapKind'] is not None:
            require(kinds == [captured['event']['trapKind']], 'c-timed-target-replay-trap-kind')
    else:
        require(captured['event']['observedErrors'] == 0, 'c-timed-target-replay-success-observation')
    return {'status': status, 'event': captured['event'], 'target': row,
            'originalTwentyControlsPassed': True, 'diagnosticOnly': True,
            'profile': 'c-context144-sync-cooperative-v1', 'runtimeLimits': dict(LIMITS),
            'activationBudget': dict(BUDGET), 'frameModuleOrdinalsAreTraceLocal': True,
            'frameToHistoricalAssertionQualified': False}


def observe(archive, output, revision):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13) and os.geteuid() != 0,
            'c-timed-diagnostic-linux-python313')
    require(os.environ.get('GITHUB_REPOSITORY') == 'KirilsTurkins/latent-service-fabric'
            and os.environ.get('GITHUB_EVENT_NAME') in ('push', 'workflow_dispatch')
            and os.environ.get('GITHUB_REF') == 'refs/heads/diag/c-timed-original-trap-20261109',
            'c-timed-diagnostic-explicit-branch')
    require(re.fullmatch('[0-9a-f]{40}', revision) is not None, 'c-timed-diagnostic-revision')
    output = output.absolute()
    require(output != ROOT and output not in ROOT.parents and ROOT not in output.parents,
            'c-timed-diagnostic-external-output')
    output = fresh(output)
    env = build_environment(output)
    env.update(CARGO_TARGET_DIR=str(ROOT / 'target'), RUSTUP_TOOLCHAIN='1.97.1',
               RUSTUP_AUTO_INSTALL='0', CARGO_BUILD_JOBS='2', CARGO_INCREMENTAL='0',
               CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0',
               CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true', CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true',
               CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true', CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
    commands = Commands(ROOT, fresh(output / 'commands'), env,
                        deadline_seconds=1500, command_seconds=1200, max_retained_bytes=16*1024**2)
    result = {'schemaVersion': 'latent.c.original-timed-trap.diagnostic.v1', 'status': 'incomplete',
              'sourceCommit': revision, 'runtimeQualification': False, 'full744Qualified': False,
              'historicalTrapCauseProved': False, 'originalGuestRebuilt': False,
              'diagnosticIoMayPerturbTiming': True, 'physicalRetirementQualified': False,
              'hostFeature': 'development-c-timed-original-trap'}
    try:
        require(commands.run('source-revision', 'git', 'rev-parse', 'HEAD').decode().strip() == revision
                and not commands.run('source-clean', 'git', 'status', '--porcelain'),
                'c-timed-diagnostic-clean-source')
        require(commands.run('rust-version', 'rustc', '--version').decode().startswith('rustc 1.97.1 ('),
                'c-timed-diagnostic-rust-version')
        raw = read_file(archive, ORIGINAL['archiveBytes'])
        result['original'] = restore(raw, output / 'original', commands.deadline)
        cargo = ('cargo', '--config', ROOT / '.cargo/managed-guest.toml')
        commands.run('normal-cli-and-signing', *cargo, 'build', '--locked', '-p', 'latent', '-p', 'latentd', '--bins',
                     '-p', 'latent-packaging', '--example', 'package', '--example', 'capsule_contracts',
                     '-p', 'latent-policy', '--example', 'capsule_authoring')
        commands.run('diagnostic-node', *cargo, 'build', '--locked', '-p', 'latentd', '--bin', 'latentd',
                     '--features', 'development-c-timed-original-trap')
        control = commands.run('authenticated-selector-control', *cargo, 'test', '--locked',
                               '-p', 'latent-wasmtime', '--lib', '--features', 'development-c-timed-original-trap',
                               'c_timed_original_fault::tests::only_the_selected_authenticated_c_invocation_is_observed',
                               '--', '--exact', '--test-threads=1')
        require(re.search(rb'^test result: ok\. 1 passed; 0 failed;', control, re.MULTILINE) is not None,
                'c-timed-diagnostic-exact-selector-control')
        debug = ROOT / 'target/debug'
        native = {'latent': debug / 'latent', 'latentd': debug / 'latentd',
                  'package': debug / 'examples/package', 'capsule_contracts': debug / 'examples/capsule_contracts',
                  'capsule_authoring': debug / 'examples/capsule_authoring'}
        before = {name: file_identity(path, 512*1024**2) for name, path in native.items()}
        result['nativeProducts'] = before
        require(time.monotonic() + 305 < commands.deadline, 'c-timed-diagnostic-replay-deadline')
        result['replay'] = replay(output / 'original', native, output / 'node')
        require(before == {name: file_identity(path, 512*1024**2) for name, path in native.items()}
                and identity(raw) == identity(read_file(archive, ORIGINAL['archiveBytes']))
                and file_identity(output / 'original/component.wasm', 8*1024**2)['sha256'] == COMPONENT
                and not commands.run('source-clean-after', 'git', 'status', '--porcelain'),
                'c-timed-diagnostic-unchanged-inputs')
        result['status'] = 'captured-nonqualifying'
        return result
    except BaseException:
        result['status'] = 'failed'
        raise
    finally:
        public = output / 'public'
        public.mkdir(exist_ok=True)
        write_json(public / 'result.json', result)
        write_json(public / 'commands.json', commands.records)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    args = parser.parse_args(argv)
    observe(args.archive.resolve(strict=True), args.output.resolve(), args.source_commit)


if __name__ == '__main__':
    main()
