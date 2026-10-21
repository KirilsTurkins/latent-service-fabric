"""Finite signed smoke test for a component built by the installed recipe."""
from contextlib import ExitStack, contextmanager
import json
from pathlib import Path
import secrets
import tempfile
import time

from tools import rust_wasi_http_runtime_node as original
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.qualify_resource_tenants import client_for_foreign
from tools.resource_tenant_node import TENANTS, require_denied_before_guest
from tools.rust_capsule_node import RecordingClient, delete_all, deploy, finish_call, start_call
from tools.rust_capsule_project import ROOT, fresh, read_json, write_json
from tools.standard_http.observations import require_zero_contact
from tools.standard_http.peer import Peer

MATERIALS = ('tools/rust_wasi_http_installed_node.py', *original.MATERIALS)


@contextmanager
def owned_cleanup(record):
    stack=ExitStack()
    try:
        yield stack
    except BaseException:
        try:
            stack.close()
        except BaseException:
            record['cleanupRefused']=True
            record['originalFailurePreserved']=True
        raise
    else:
        stack.close()


def run(artifact, native, output, *, deadline):
    output = fresh(output)
    names = ('component.wasm', 'BUILD-COMPLETE.json', 'source-inputs.json', 'recipe-inputs.json',
        'build-observation.json', 'capsule.json', 'package-source.json', 'rust-http-runtime.json')
    before = {name: file_identity(artifact/name) for name in names}
    binaries = {name: file_identity(path, 512*1024**2) for name, path in native.items()}
    materials = {name: file_identity(ROOT/name) for name in MATERIALS}
    record = {'schemaVersion': 'latent.rust.wasi-http.installed-node.v1', 'status': 'incomplete',
        'originalInstalledBuild': before, 'nativeProducts': binaries, 'materials': materials,
        'cases': [], 'preEntryRefusals': [], 'fullRuntimeMatrixRepeated': False,
        'publisherAuthenticated': False, 'fullReleasedFrontendQualified': False}
    stage = 'normal-neutral-signing'
    try:
        signed = output/'releases'
        result = run_bounded_result([str(native['capsule_authoring']), 'demo-sign-neutral-resources',
            str(signed), str(artifact)], output, build_environment(output),
            timeout_seconds=min(30, deadline-time.monotonic()), max_output_bytes=65536)
        record['signingCommand']={'exitCode':result.returncode}
        for suffix,raw in (('stdout',result.stdout),('stderr',result.stderr)):
            path=output/('signing.'+suffix);path.write_bytes(raw)
            record['signingCommand'][suffix]=file_identity(path,65536)
        require(result.returncode == 0, 'installed-rust-normal-signing')
        record['signing'] = original.checked_signing(artifact, signed, before)
        with tempfile.TemporaryDirectory(prefix='lsf-installed-rust-http-') as temporary, \
                owned_cancellation() as cancellation, owned_cleanup(record) as cleanup:
            work = Path(temporary)
            for name in ('node', 'examples', 'peers'):
                (work/name).mkdir(mode=0o700)
            peers, credentials, protected = {}, {}, []
            for tenant in TENANTS:
                directory = work/'peers'/tenant
                directory.mkdir(mode=0o700)
                secret = ('Bearer '+secrets.token_hex(32)).encode()
                protected.append(secret)
                credential = directory/'authorization'
                credential.write_bytes(secret); credential.chmod(0o600)
                credentials[tenant] = credential
                peers[tenant] = Peer(secret, maximum_seconds=120)
                cleanup.callback(peers[tenant].close)
            client = RecordingClient(native['latent'], work/'examples', cancellation,
                min(deadline, time.monotonic()+110), evidence=output/'examples-controls')
            config = original.configuration(work/'node', signed, peers, credentials)
            stage = 'one-cell-current-node'
            node = connect(client, native['latentd'], work/'node', config, 'examples', 1)
            cleanup.callback(node.close)
            clients = {'examples': client,
                'foreign': client_for_foreign(client, node, work/'foreign', output/'foreign-controls')}
            probe = Probe(node, binaries['latentd'])
            source = signed/original.SERVICE
            targets, publications = {}, {}
            stage = 'independent-tenant-publication-and-denial'
            for tenant in TENANTS:
                selected = clients[tenant]
                published = selected.call('release', 'publish-package', source/'package', '--evidence',
                    source/'evidence/index.json', '--operation-id', 'installed-rust-publish-'+tenant,
                    '--expected-generation', '0')
                require(published['outcomeKnown'] is True
                    and published['data']['release']['digest'] == before['component.wasm']['sha256'],
                    'installed-rust-original-component-publication')
                publication = published['data']['operation']['publication']['id']
                publications[tenant] = publication
                manifest = selected.directory/'deployment.json'
                write_json(manifest, original.deployment(read_json(source/'deployment.json'), tenant))
                target = deploy(selected, manifest, publication)
                snapshots = {name: peer.observation() for name, peer in peers.items()}
                pending = start_call(selected, target, 'greeting', 'greet',
                    ['alpha|waki|json|'+peers[tenant].url('domain-json')], 'installed-'+tenant+'-ungranted')
                denied = finish_call(selected, pending)
                require_denied_before_guest(denied)
                require(all(original.unsigned(value) == 0
                    for key, value in denied['response']['data']['consumption'].items()
                    if key != 'wallTimeMicros'), 'installed-rust-no-ungranted-dispatch-or-fuel')
                for name, peer in peers.items():
                    peer.poll(0); require_zero_contact(snapshots[name], peer.observation())
                retirement = original.retire(selected, probe, target, output, tenant+'-denied',
                    population=len(targets)+1)
                record['preEntryRefusals'].append({'tenant': tenant, 'invocation': denied, 'retirement': retirement})
                grants = original.grant(selected, node, publication, tenant, peers[tenant])
                targets[tenant] = deploy(selected, manifest, publication, generation=str(target['generation']), grants=grants)
            require(publications['examples'] != publications['foreign'], 'installed-rust-independent-publications')
            record['publications'] = publications
            stage = 'both-ordinary-parsed-clients-and-opposite-fresh'
            spec = ('installed-json', 'json', '/conformance/json', original.DOMAIN_TEXT, 1, 'domain-json', '')
            for tenant, library, alias in (('examples', 'waki', 'alpha'), ('foreign', 'golem', 'delta'),
                    ('examples', 'golem', 'delta'), ('foreign', 'waki', 'alpha')):
                label = tenant+'-'+library
                row = original.invoke(clients[tenant], node, targets[tenant], peers, tenant, library,
                    alias, spec, probe, output, label)
                record['cases'].append(row)
                write_json(output/('case-'+label+'.json'), row)
            stage = 'final-physical-provider-retirement-and-shutdown'
            for index, tenant in enumerate(TENANTS):
                original.retire(clients[tenant], probe, targets[tenant], output, tenant+'-final',
                    population=len(TENANTS)-index)
                delete_all(clients[tenant], [targets[tenant]['name']])
            stop(client, node)
            record['shutdown'] = stopped_record(node)
            require(record['shutdown']['reaped'] is True and record['shutdown']['record']['clean'] is True,
                'installed-rust-clean-physical-node-shutdown')
            record['peers'] = {}
            for tenant, peer in peers.items():
                observed = peer.close()
                raw = json.dumps(observed, ensure_ascii=True).encode()
                require(all(secret not in raw and secret.removeprefix(b'Bearer ') not in raw
                    for secret in protected), 'installed-rust-no-controlled-credentials-retained')
                record['peers'][tenant] = original.check_peer_final(observed, ['domain-json', 'domain-json'])
                write_json(output/(tenant+'-peer-final.json'), observed)
            record['startup'] = node.startup_record
        require(before == {name: file_identity(artifact/name) for name in names}
            and binaries == {name: file_identity(path, 512*1024**2) for name, path in native.items()}
            and materials == {name: file_identity(ROOT/name) for name in MATERIALS}
            and time.monotonic() < deadline, 'installed-rust-final-source-and-product-identity')
        record.update(status='passed', guestExecutions=4, invocationAttempts=6, preEntryRefusalsCount=2,
            peerContacts=4, signedInstalledRecipeQualification=True)
        write_json(output/'qualification.json', record)
        return record
    except BaseException:
        record.update(status='failed', stage=stage)
        try:
            write_json(output/'FAILED.json', record)
        except OSError:
            pass
        raise
