"""Failure-only private node replay; bounded numeric Wasm frames, never qualification."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sys
import tempfile
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import diagnose_go_entry as entry
from tools import diagnose_go_timer_failure as host
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import Process, WorkflowError, read_json, require, stopped_record, write_json
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, digest, fresh, read_file

PATHS = ('crates/latent-wasmtime/src/containment.rs', 'crates/latent-wasmtime/src/config/engine.rs')
PREFIX = b'LSF_GO_ENTRY_FRAMES '
OBSERVER = '''
    // Private failure-only build: numbers only, with no names, paths or messages.
    if let Some(trace) = error.downcast_ref::<wasmtime::WasmBacktrace>() {
        let frames: Vec<_> = trace
            .frames()
            .iter()
            .take(32)
            .map(|frame| {
                serde_json::json!({
                    "functionIndex": frame.func_index(), "functionOffset": frame.func_offset(),
                    "moduleOffset": frame.module_offset()
                })
            })
            .collect();
        eprintln!(
            "LSF_GO_ENTRY_FRAMES {}",
            serde_json::json!({
                "available": true, "truncated": trace.frames().len() > 32, "frames": frames
            })
        );
    } else {
        eprintln!(
            "LSF_GO_ENTRY_FRAMES {}",
            serde_json::json!({
                "available": false, "truncated": false, "frames": []
            })
        );
    }
'''


def overlay_sources(root: Path, output: Path) -> tuple[dict, list[tuple[Path, Path]]]:
    originals = {name: read_file(root/name) for name in PATHS}
    containment = originals[PATHS[0]].decode()
    begin = containment.index('pub(crate) fn classify_runtime_error(')
    signature = ') -> Result<GuestOutcome, PlatformError> {'
    offset = containment.index(signature, begin)+len(signature)
    engine = originals[PATHS[1]].decode()
    require(engine.count('WasmBacktraceDetails::Disable') == 1, 'go-entry-frame-details-preimage')
    changed = {PATHS[0]: containment[:offset]+OBSERVER+containment[offset:],
        PATHS[1]: host.once(engine, 'wasm_backtrace_max_frames(None)',
                           'wasm_backtrace_max_frames(std::num::NonZeroUsize::new(32))')}
    identities, overlays = {}, []
    for name in PATHS:
        private = output/Path(name).name
        private.write_text(changed[name], encoding='utf-8', newline='\n')
        identities[name] = {'original': digest(originals[name]), 'private': digest(read_file(private))}
        overlays.append((private, root/name))
    return identities, overlays


def numeric_frames(data: bytes) -> dict:
    require(len(data) <= 65536, 'go-entry-frame-output-bound')
    rows = [line[len(PREFIX):] for line in data.splitlines() if line.startswith(PREFIX)]
    require(len(rows) == 1 and len(rows[0]) <= 8192, 'go-entry-frame-record-count')
    value = json.loads(rows[0])
    require(isinstance(value, dict) and set(value) == {'available', 'truncated', 'frames'}
        and type(value['available']) is bool and type(value['truncated']) is bool
        and isinstance(value['frames'], list) and len(value['frames']) <= 32, 'go-entry-frame-shape')
    require(value['available'] or not value['frames'] and not value['truncated'], 'go-entry-frame-unavailable')
    for frame in value['frames']:
        require(isinstance(frame, dict) and set(frame) == {'functionIndex', 'functionOffset', 'moduleOffset'}
            and type(frame['functionIndex']) is int and 0 <= frame['functionIndex'] < 2**32
            and all(frame[key] is None or type(frame[key]) is int and 0 <= frame[key] < 2**53
                    for key in ('functionOffset', 'moduleOffset')), 'go-entry-frame-numeric-shape')
    return value


def build_command(root, overlays, environment, tools, context):
    require(len(overlays) == 2 and {original.relative_to(root).as_posix() for _, original in overlays} == set(PATHS),
            'go-entry-frame-source-set')
    environment = dict(environment)
    for key in ('TEMP', 'TMP', 'TMPDIR'):
        environment.pop(key, None)
    require(len(environment) <= 64 and all(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', key)
        and isinstance(value, str) and len(value) <= 32768 and '\0' not in value
        for key, value in environment.items()), 'go-entry-frame-environment')
    command = [tools['sudo'], '-n', '--', tools['bwrap'], '--unshare-pid', '--unshare-ipc', '--unshare-uts',
        '--die-with-parent', '--new-session', '--bind', '/', '/', '--proc', '/proc', '--dev', '/dev',
        '--cap-drop', 'ALL', '--cap-add', 'CAP_SETUID', '--cap-add', 'CAP_SETGID', '--cap-add', 'CAP_SETPCAP', '--clearenv']
    for key, value in sorted(environment.items()):
        command += ['--setenv', key, value]
    for private, original in overlays:
        command += ['--ro-bind', str(private), str(original)]
    return command+['--chdir', str(root), tools['setpriv'], '--reuid', str(context['uid']),
        '--regid', str(context['gid']), '--clear-groups', '--bounding-set=-all', '--inh-caps=-all',
        '--ambient-caps=-all', '--no-new-privs', str(Path(sys.executable).resolve()), '-I', '-B',
        str(host.frame_preflight_source(root)), json.dumps(context, separators=(',', ':')),
        tools['cargo'], '--config', '.cargo/managed-guest.toml', 'build', '--offline', '--locked',
        '-p', 'latentd', '--bin', 'latentd']


def release_identity(releases: Path) -> str:
    rows = []
    total = 0
    for path in sorted(releases.rglob('*')):
        require(not path.is_symlink(), 'go-entry-frame-release-symlink')
        if path.is_dir():
            continue
        identity = file_identity(path, 64*1024**2)
        total += identity['bytes']
        rows.append((path.relative_to(releases).as_posix(), identity))
        require(len(rows) <= 128 and total <= 128*1024**2, 'go-entry-frame-release-bound')
    require(rows, 'go-entry-frame-release-empty')
    return digest(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode())


def replay(releases, binaries, output, deadline):
    """Replay only the original integer control, retaining no raw node stderr."""
    output = fresh(output)
    expires = min(time.monotonic()+90, deadline)
    record = {'qualification': False, 'status': 'in-progress', 'stage': 'node', 'function': 'integer-control'}
    service = None
    try:
        environment = build_environment(output)
        with tempfile.TemporaryDirectory(prefix='lsf-go-entry-frame-') as private, \
                owned_cancellation() as cancellation, ExitStack() as cleanup:
            work = Path(private)
            for name in ('client', 'node', 'peer'):
                (work/name).mkdir(mode=0o700)
            credential = work/'peer/authorization'
            credential.write_text('Bearer '+secrets.token_hex(32), encoding='ascii')
            credential.chmod(0o600)
            client = entry.node.RecordingClient(binaries['latent'], work/'client', cancellation, expires,
                evidence=output/'controls', invocation_timeout_millis=120000)
            peer = Process([sys.executable, str(ROOT/entry.node.PEER_SOURCE), '--credential', str(credential)],
                work/'peer', environment, cancellation, maximum=65536)
            cleanup.callback(peer.close)
            startup = peer.line(min(expires, time.monotonic()+10))
            config = entry.node.configuration(work/'node', releases, startup, credential)
            service = entry.node.connect(client, binaries['latentd'], work/'node', config, 'examples', 1)
            cleanup.callback(service.close)
            probe = entry.node.Probe(service, file_identity(binaries['latentd']))
            record['baselineOs'] = probe.sample()
            source = releases/'go-standard-http'
            published = client.call('release', 'publish-package', source/'package', '--evidence', source/'evidence/index.json',
                '--operation-id', 'entry-diagnostic-publish', '--expected-generation', '0')
            publication = published['data']['operation']['publication']['id']
            runtime, _authorized = entry.node.grants(client, service, publication, startup['origins']['primary'])
            target = entry.node.deploy(client, source/'deployment.json', publication, grants=runtime)
            record['stage'] = 'entry'
            record['entry'] = entry.invoke_signature(client, target, 'integer-control', [], 'entry-integer-control')
            write_json(output/'entry.json', record)
            record['outcome'] = entry.outcome(record['entry'], 42)
            record['stage'] = 'retirement'
            entry.node.retire_case(client, probe, target, output, 'entry-integer-control')
            entry.node.delete_all(client, [target['name']])
            entry.node.stop(client, service)
            record['shutdown'] = stopped_record(service)
            require(record['shutdown']['reaped'] and record['shutdown']['record']['clean'], 'go-entry-frame-clean-shutdown')
            peer.stop()
            peer_record = json.loads(bytes(peer.buffers[0]).splitlines()[0])
            entry.node.validate_peer(peer_record)
            require(all(type(peer_record[key]) is int and peer_record[key] == 0
                        for key in ('acceptedConnections', 'startedRequests', 'committedMutations'))
                and not peer_record['requests'] and peer.owner.finished, 'go-entry-frame-peer-contact')
            record['peerReaped'] = True
            record['peerContacts'] = 0
        record.update(status='observed', stage='complete')
    except Exception:
        record['status'] = 'incomplete'
        raise
    finally:
        if service is not None:
            try:
                record['numericFrames'] = numeric_frames(bytes(service.buffers[1]))
            except (ValueError, TypeError, KeyError, WorkflowError):
                record['frameCapture'] = 'unavailable-or-refused'
        write_json(output/'observation.json', record)
    return record


def diagnose(diagnostic: Path, native: Path, output: Path) -> dict:
    output = fresh(output)
    deadline = time.monotonic()+600
    record = {'schemaVersion': 'latent.go.private-entry-frames.v1', 'qualification': False,
        'status': 'incomplete', 'stage': 'inputs', 'limits': {'overallSeconds': 600, 'buildSeconds': 450,
        'nodeSeconds': 90, 'frames': 32, 'capturedOutputBytes': 1048576},
        'rawNativeOutputRetained': False, 'privateBinaryPublished': False,
        'ephemeralTargetDisposition': 'diagnostic-only-after-all-acceptance'}
    try:
        supporting = {name: digest(read_file(ROOT/name)) for name in ('tools/diagnose_go_entry_frames.py',
            'tools/diagnose_go_entry.py', 'tools/diagnose_go_timer_failure.py', host.FRAME_PREFLIGHT_SOURCE)}
        record['supportingSources'] = supporting
        observation = read_json(diagnostic/'observation.json')
        require(observation['status'] == 'observed' and observation['qualification'] is False, 'go-entry-frame-original-observation')
        row = next(value for value in observation['variants'] if value['variant'] == 'without-http')
        require(row['compileExitCode'] == 0 and row['node']['status'] == 'observed'
            and row['node']['signatures'][0]['function'] == 'integer-control'
            and row['node']['signatures'][0]['outcome'] == 'trapped', 'go-entry-frame-original-entry')
        component = diagnostic/'without-http/build/component.wasm'
        require(file_identity(component, 64*1024**2) == row['component'], 'go-entry-frame-component-identity')
        require(row['node']['signatures'][0]['entry']['response']['data']['resolvedRevision']['releaseDigest']
            == row['component']['sha256'], 'go-entry-frame-original-release')
        releases = diagnostic/'without-http/node/releases'
        signed = release_identity(releases)
        receipt = read_json(native/'qualification.json')
        require(receipt.get('schemaVersion') == 'latent.go-capsule.qualification.v1'
            and receipt['status'] == 'passed', 'go-entry-frame-frozen-qualification')
        binaries = {name: native/'native-binaries'/key.replace('/', '-') for name, key in entry.NATIVE_NAMES.items()}
        identities = {name: file_identity(path, 512*1024**2) for name, path in binaries.items()}
        require(identities == observation['binaries'] and all(identities[name] == receipt['binaries'][key]
            for name, key in entry.NATIVE_NAMES.items()), 'go-entry-frame-frozen-binaries')
        context = host.frame_host_context()
        tools = {name: shutil.which(name) for name in ('cargo', 'bwrap', 'sudo', 'setpriv')}
        require(all(tools.values()), 'go-entry-frame-existing-tools')
        overlays_root = fresh(output/'source-overlays')
        sources, overlays = overlay_sources(ROOT, overlays_root)
        record.update(component=row['component'], signedRelease=signed, sourceOverlays=sources,
            originalObservation=file_identity(diagnostic/'observation.json'), stage='private-build')
        environment = build_environment(output)
        environment.update(CARGO_INCREMENTAL='0', CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0',
            CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true', CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true',
            CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true', CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
        target = Path(os.environ.get('CARGO_TARGET_DIR', str(ROOT/'target'))).resolve()
        require(target.is_dir(), 'go-entry-frame-existing-target')
        environment['CARGO_TARGET_DIR'] = str(target)
        command = build_command(ROOT, overlays, environment, tools, context)
        built = run_bounded_result(command, ROOT, environment, min(450, deadline-time.monotonic()), 1048576)
        record.update(buildExitCode=built.returncode, hostPreflight=host.frame_host_observation(built.stdout+b'\n'+built.stderr),
            compilerErrorCodes=sorted(set(code.decode() for code in re.findall(rb'error\[(E[0-9]{4})\]', built.stderr)))[:16])
        require(built.returncode == 0 and record['hostPreflight'] is not None, 'go-entry-frame-private-build-failed')
        private_host = output/'private-latentd'
        shutil.copy2(target/'debug/latentd', private_host)
        record['privateHost'] = file_identity(private_host, 512*1024**2)
        require(record['privateHost'] != identities['latentd'], 'go-entry-frame-private-host-unchanged')
        require(file_identity(component, 64*1024**2) == row['component']
            and release_identity(releases) == signed and identities == {
                name: file_identity(path, 512*1024**2) for name, path in binaries.items()}
            and all(digest(read_file(ROOT/name)) == value['original'] for name, value in sources.items())
            and all(digest(read_file(private)) == sources[original.relative_to(ROOT).as_posix()]['private']
                    for private, original in overlays),
            'go-entry-frame-input-changed-before-replay')
        record['stage'] = 'private-replay'
        record['replay'] = replay(releases, {**binaries, 'latentd': private_host}, output/'node', deadline)
        require(record['replay']['entry']['response']['data']['resolvedRevision']['releaseDigest']
            == row['component']['sha256'], 'go-entry-frame-replay-release')
        record.update(status='observed', stage='complete')
    except Exception as error:
        record['failureClass'] = type(error).__name__ if type(error).__name__ in {
            'WorkflowError', 'ValueError', 'KeyError', 'TypeError', 'FileNotFoundError', 'PermissionError', 'OSError'} else 'Other'
        if (output/'node/observation.json').is_file():
            record['replay'] = read_json(output/'node/observation.json')
    finally:
        intact = True
        if 'supportingSources' in record:
            record['supportingSourceUnchanged'] = all(digest(read_file(ROOT/name)) == value
                for name, value in record['supportingSources'].items())
            intact = record['supportingSourceUnchanged']
        if 'sourceOverlays' in record:
            record['originalSourceUnchanged'] = all(digest(read_file(ROOT/name)) == value['original']
                for name, value in record['sourceOverlays'].items())
            record['originalComponentUnchanged'] = file_identity(component, 64*1024**2) == row['component']
            record['signedReleaseUnchanged'] = release_identity(releases) == signed
            record['frozenBinariesUnchanged'] = identities == {
                name: file_identity(path, 512*1024**2) for name, path in binaries.items()}
            record['privateOverlaysUnchanged'] = all(digest(read_file(private))
                == sources[original.relative_to(ROOT).as_posix()]['private'] for private, original in overlays)
            intact = intact and all(record[key] for key in ('originalSourceUnchanged', 'originalComponentUnchanged',
                'signedReleaseUnchanged', 'frozenBinariesUnchanged', 'privateOverlaysUnchanged'))
            if not intact:
                record['status'] = 'incomplete'
        write_json(output/'observation.json', record)
        require(intact, 'go-entry-frame-original-input-mutated')
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--diagnostic', type=Path, required=True)
    parser.add_argument('--native-qualification', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(diagnose(arguments.diagnostic.resolve(), arguments.native_qualification.resolve(), arguments.output.resolve())))
