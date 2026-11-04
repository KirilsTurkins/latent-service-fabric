"""Observe one retained ordinary libfetch POST against the existing peer."""
from __future__ import annotations

import json
from pathlib import Path
import secrets
import tempfile
import time

from tools import c_http_post_companion as post, c_thread_runtime_node as owner
from tools.c_http_media_peer import MediaPeer
from tools.c_guest.standard_facilities import FETCH_STANDARD_PROFILE
from tools.phase2_operator_process import require, stopped_record
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, read_json, write_json
from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.standard_http.observations import validate


def run(artifact: Path, native: dict, output: Path):
    output = fresh(output)
    component = file_identity(artifact / 'component.wasm', 8 * 1024**2)
    before = {name: file_identity(path) for name, path in native.items()}
    commands = Commands(ROOT, fresh(output / 'commands'), build_environment(output),
                        deadline_seconds=300, command_seconds=60)
    record = {'schemaVersion': 'latent.c.http-media.node.v1', 'status': 'incomplete',
              'component': component, 'native': before, 'historicalComponentReused': True,
              'oneOrdinaryPostOnly': True, 'full690Qualified': False}
    stage, failed = 'sign', False
    try:
        signed = output / 'signed'
        commands.run('c-media-sign', native['capsule_authoring'], 'demo-sign', signed, artifact)
        releases = read_json(signed / 'release-set.json')['releases']
        require(len(releases) == 1 and releases[0]['componentDigest'] == component['sha256'],
                'c-media-one-signed-component')
        with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix='lsf-c-media-') as temporary, \
                owner.owned_cleanup(record) as cleanup:
            work = Path(temporary)
            for name in ('client', 'node', 'credentials'):
                (work / name).mkdir(mode=0o700)
            secret = b'Bearer ' + secrets.token_hex(32).encode('ascii')
            credential = work / 'credentials/peer'
            credential.write_bytes(secret); credential.chmod(0o600)
            peer = MediaPeer(secret, maximum_seconds=max(1, min(300, int(commands.deadline - time.monotonic()))))
            cleanup.callback(peer.close)
            client = owner.RecordingClient(native['latent'], work / 'client', cancellation,
                min(commands.deadline, time.monotonic() + 240), evidence=output / 'controls')
            config, settings = owner.configure_base(work / 'node', signed, peer.origin()['port'], language='c')
            owner.configure_libucl(settings, read_json(artifact / 'capsule.json'), peer, credential)
            config.write_bytes((json.dumps(settings, sort_keys=True, separators=(',', ':')) + '\n').encode())
            stage = 'node'
            node = owner.connect(client, native['latentd'], work / 'node', config, 'examples', 0)
            cleanup.callback(node.close)
            record['startup'] = node.startup_record
            probe = owner.Probe(node, before['latentd'])
            source = signed / owner.SERVICE
            published = client.call('release', 'publish-package', source / 'package',
                '--evidence', source / 'evidence/index.json', '--operation-id', 'c-media-publish',
                '--expected-generation', '0')
            require(published['outcomeKnown'] is True and published['data']['release']['digest'] == component['sha256'],
                    'c-media-signed-admission')
            publication = published['data']['operation']['publication']['id']
            target = owner.deploy(client, source / 'deployment.json', publication)
            require(target['grants'] == [], 'c-media-no-ambient-grants')
            grants = post.install(client, node, target, peer.origin())
            target = owner.deploy(client, source / 'deployment.json', publication,
                                  generation=str(target['generation']), grants=grants)
            stage = 'one-ordinary-post'
            record['case'] = post.cell(client, node, probe, target, peer, output, 'post-echo')
            record['media'] = peer.media_observation()
            write_json(output / 'media-observation.json', record['media'])
            require(record['case']['case'] == 'post-echo'
                    and peer.observation()['startedRequests'] == 1, 'c-media-exact-one-contact')
            owner.delete_all(client, [target['name']])
            record['afterDeletes'] = owner.sample(client, probe, 'c-media-after-deletes', 0)
            owner.stop(client, node); record['nodeShutdown'] = stopped_record(node)
            record['peerShutdown'] = peer.close(); validate(record['peerShutdown'])
            require(record['peerShutdown']['openConnections'] == record['peerShutdown']['listeningOrigins'] == 0,
                    'c-media-stopped-peer')
            cancellation.check()
        require(record['media']['exactMatch'] is True, 'c-media-exact-content-type-mismatch')
        require(component == file_identity(artifact / 'component.wasm', 8 * 1024**2)
                and before == {name: file_identity(path) for name, path in native.items()}
                and time.monotonic() < commands.deadline and client.calls <= 384,
                'c-media-final-original-inputs-and-deadline')
        record.update(status='passed', runtimeProfile=FETCH_STANDARD_PROFILE,
                      cliCalls=client.calls, commands=commands.records)
        write_json(output / 'qualified.json', record)
        return record
    except BaseException:
        failed = True
        record.update(status='failed', stage=stage)
        raise
    finally:
        if failed:
            write_json(output / 'FAILED.json', record)
