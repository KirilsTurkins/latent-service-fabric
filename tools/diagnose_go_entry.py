"""Bounded signed v4 import differential; observations never qualify HTTP."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import secrets
import sys
import tempfile
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import go_standard_http_node as node
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.go_standard_http_project import project
from tools.phase2_operator_process import Process, read_json, require, write_json, stopped_record
from tools.phase3_resource_identity import file_identity
from tools.qualify_go_standard_http import NATIVE_NAMES
from tools.rust_capsule_project import ROOT, digest, fresh, read_file

VARIANTS = ('without-http', 'with-http-import')


def capture(directory: Path, variant: str) -> Path:
    require(variant in VARIANTS, 'go-entry-unknown-variant')
    app = project(directory)
    source = ('package export_examples_go_standard_http_api\n\n'
              + ('import _ "net/http"\n\n' if variant == 'with-http-import' else '')
              + 'func Run(which uint32, address string) string { return "entered" }\n').encode()
    (app/'src/main.go').write_bytes(source)
    lock = read_json(app/'sdk-lock.json')
    lock['template'] = {'name': 'go-entry-'+variant, 'sourceDigest': digest(source),
                        'witDigest': digest(read_file(app/'wit/world.wit'))}
    (app/'sdk-lock.json').write_text(json.dumps(lock, indent=2)+'\n', encoding='utf-8')
    return app


def outcome(row: dict) -> str:
    require(row['processReaped'] is True and type(row['exitCode']) is int
            and row['exitCode'] in {0, 4}, 'go-entry-cli-outcome')
    consumption = row['response']['data']['consumption']
    require(all(type(consumption[key]) is int and consumption[key] == 0
                for key in ('outboundRequests', 'childCalls', 'effectCount')),
            'go-entry-external-effect')
    if row['exitCode'] == 0:
        require(row['decoded'] == ['entered'], 'go-entry-constant-result')
        return 'returned'
    require(row['decoded'] is None and row['response']['data']['terminalState'] == 'guest_trap',
            'go-entry-not-a-guest-trap')
    return 'trapped'


def observe(artifact: Path, binaries: dict, output: Path, deadline: float) -> dict:
    """Use ordinary signing/admission/owners, retaining only public CLI errors."""
    output = fresh(output)
    expires = min(time.monotonic()+90, deadline)
    record = {'qualification': False, 'status': 'in-progress', 'stage': 'sign'}
    try:
        environment = build_environment(output)
        signed = output/'releases'
        result = run_bounded_result([str(binaries['capsule_authoring']), 'demo-sign', str(signed), str(artifact)],
            output, environment, min(30, expires-time.monotonic()), 65536)
        require(result.returncode == 0, 'go-entry-signing-failed')
        with tempfile.TemporaryDirectory(prefix='lsf-go-entry-') as private, \
                owned_cancellation() as cancellation, ExitStack() as cleanup:
            work = Path(private)
            for name in ('client', 'node', 'peer'):
                (work/name).mkdir(mode=0o700)
            credential = work/'peer/authorization'
            credential.write_text('Bearer '+secrets.token_hex(32), encoding='ascii')
            credential.chmod(0o600)
            client = node.RecordingClient(binaries['latent'], work/'client', cancellation, expires,
                evidence=output/'controls', invocation_timeout_millis=120000)
            peer = Process([sys.executable, str(ROOT/node.PEER_SOURCE), '--credential', str(credential)],
                           work/'peer', environment, cancellation, maximum=65536)
            cleanup.callback(peer.close)
            startup = peer.line(min(expires, time.monotonic()+10))
            config = node.configuration(work/'node', signed, startup, credential)
            record.update(stage='node', configurationIdentity=file_identity(config))
            service = node.connect(client, binaries['latentd'], work/'node', config, 'examples', 1)
            cleanup.callback(service.close)
            probe = node.Probe(service, file_identity(binaries['latentd']))
            record['baselineOs'] = probe.sample()
            source = signed/'go-standard-http'
            published = client.call('release', 'publish-package', source/'package', '--evidence', source/'evidence/index.json',
                '--operation-id', 'entry-diagnostic-publish', '--expected-generation', '0')
            publication = published['data']['operation']['publication']['id']
            origin = startup['origins']['primary']
            _runtime, authorized = node.grants(client, service, publication, origin)
            target = node.deploy(client, source/'deployment.json', publication, grants=authorized)
            record['stage'] = 'entry'
            record['entry'] = node.invoke(client, target, 25,
                f"http://{origin['host']}:{origin['port']}/conformance/json", 'entry-differential')
            # Retain a trap before any predicate or cleanup that might also fail.
            write_json(output/'entry.json', record)
            record['outcome'] = outcome(record['entry'])
            record['stage'] = 'retirement'
            node.retire_case(client, probe, target, output, 'entry-differential')
            node.delete_all(client, [target['name']])
            node.stop(client, service)
            record['shutdown'] = stopped_record(service)
            require(record['shutdown']['reaped'] and record['shutdown']['record']['clean'], 'go-entry-node-clean-shutdown')
            peer.stop()
            peer_record = json.loads(bytes(peer.buffers[0]).splitlines()[0])
            node.validate_peer(peer_record)
            require(all(peer_record[key] == 0 for key in ('acceptedConnections', 'startedRequests', 'committedMutations'))
                    and not peer_record['requests'], 'go-entry-peer-contact')
            record.update(peer=peer_record, peerReaped=peer.owner.finished)
        record.update(status='observed', stage='complete')
        return record
    except Exception:
        record['status'] = 'incomplete'
        raise
    finally:
        write_json(output/'observation.json', record)


def diagnose(output: Path, native: Path) -> dict:
    output = fresh(output)
    deadline = time.monotonic()+600
    record = {'schemaVersion': 'latent.go.entry-import-diagnostic.v1', 'qualification': False,
              'status': 'in-progress', 'variants': [],
              'limits': {'overallSeconds': 600, 'compileSeconds': 180, 'nodeSeconds': 90}}
    stage = 'native-products'
    try:
        sources = {name: file_identity(ROOT/name) for name in ('tools/diagnose_go_entry.py',
            'tools/go_standard_http_project.py', 'tools/go_standard_http_node.py',
            'tools/qualify_go_standard_http.py', 'sdk/go-guest/runtime/standard-http-conformance/world.wit')}
        record['sources'] = sources
        receipt_path = native/'qualification.json'
        receipt = read_json(receipt_path)
        require(receipt.get('schemaVersion') == 'latent.go-capsule.qualification.v1'
                and receipt.get('status') == 'passed', 'go-entry-normal-native-qualification-required')
        binaries = {name: native/'native-binaries'/key.replace('/', '-') for name, key in NATIVE_NAMES.items()}
        identities = {name: file_identity(path, 512*1024**2) for name, path in binaries.items()}
        require(all(identities[name] == receipt['binaries'][key] for name, key in NATIVE_NAMES.items()),
                'go-entry-frozen-native-products-mismatch')
        before = file_identity(receipt_path)
        record.update(nativeQualification=before, binaries=identities)
        for variant in VARIANTS:
            require(before == file_identity(receipt_path) and identities == {
                name: file_identity(path, 512*1024**2) for name, path in binaries.items()}, 'go-entry-native-products-changed')
            stage = variant
            owned = output/variant
            owned.mkdir()
            app = capture(owned/'project', variant)
            row = {'variant': variant, 'source': file_identity(app/'src/main.go'),
                   'wit': file_identity(app/'wit/world.wit'), 'qualification': False}
            record['variants'].append(row)
            command = [sys.executable, str(ROOT/'tools/go_capsule.py'), 'build', str(app),
                '--output', str(owned/'build'), '--repository', 'https://github.com/KirilsTurkins/latent-service-fabric',
                '--contracts-tool', str(binaries['capsule_contracts']), '--packager', str(binaries['package'])]
            maximum = min(180, deadline-time.monotonic())
            require(maximum > 0, 'go-entry-original-deadline')
            write_json(owned/'compiler-command.json', {'command': command, 'maximumSeconds': maximum})
            compiled = run_bounded_result(command, ROOT, build_environment(owned), maximum, 2*1024**2)
            for name in ('stdout', 'stderr'):
                (owned/('compiler.'+name+'.txt')).write_bytes(getattr(compiled, name))
            row['compileExitCode'] = compiled.returncode
            if compiled.returncode == 0:
                row['component'] = file_identity(owned/'build/component.wasm', 64*1024**2)
                try:
                    row['node'] = observe(owned/'build', {k: binaries[k] for k in ('latent', 'latentd', 'capsule_authoring')},
                                          owned/'node', deadline)
                except Exception:
                    row['node'] = read_json(owned/'node/observation.json')
                    row['node']['status'] = 'incomplete'
            write_json(output/(variant+'.json'), record)
        require(before == file_identity(receipt_path) and identities == {
            name: file_identity(path, 512*1024**2) for name, path in binaries.items()}, 'go-entry-native-products-changed')
        require(time.monotonic() < deadline, 'go-entry-original-deadline')
        require(sources == {name: file_identity(ROOT/name) for name in sources}, 'go-entry-original-sources-changed')
        complete = all(row.get('node', {}).get('status') == 'observed' for row in record['variants'])
        record.update(status='observed' if complete else 'incomplete', stage='complete')
        return record
    finally:
        record.setdefault('stage', stage)
        write_json(output/'observation.json', record)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--native-qualification', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(diagnose(args.output.resolve(), args.native_qualification.resolve())))
