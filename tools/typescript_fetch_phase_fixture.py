"""Published default clients on the explicit phase contract; no native promotion."""
from __future__ import annotations
import json
import hashlib
from pathlib import Path

from tools import typescript_published_fetch_fixture as published
from tools.http_phase_wit import nominal_type_owner
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, digest, read_file
from tools.standard_http.peer import Peer
from tools.standard_http.observations import validate
from tools.standard_http.vectors import DOMAIN, json_bytes

SOURCE = 'sdk/typescript-guest/probes/fetch-phases/main.ts'
HTTP = 'latent:http/phase-timing@0.4.0'
PROFILE = 'lsf-fetch-phase-buffered-v2'
PRIVATE_NAME = 'outside-fetch-phase'
EXECUTION_PROFILE = 'typescript-phase-published-clients-fuel-v1'
INITIAL_CPU_FUEL = 2_000_000_000
VECTORS = (
    ('ky-json', 0, 'domain-json', None),
    ('wretch-json', 1, 'domain-json', None),
    ('outside-json', 2, 'domain-json', None),
    ('ky-http404', 3, 'http-404', '1|ky:error:404'),
    ('wretch-http404', 4, 'http-404', '1|wretch:error:404'),
    ('observed-empty-clone', 7, 'http-404', 'wire:404:""|fresh=1'),
    ('latin1-clone', 8, 'http-500', 'wire:500:" Caf\u00ff "|fresh=1'),
    ('abort-headers', 9, 'pending-headers', 'abort:exact-reason|fresh=1'),
    ('abort-body', 9, 'partial-body', 'abort:exact-reason|fresh=1'),
    ('uncertain-post', 11, 'commit-close', 'uncertain:true|fresh=1'),
    ('denied-target', 12, 'denied-target', 'denied:no-contact|fresh=1'),
    ('public-guest-extension', 13, 'domain-json', 'extension:1:'+json_bytes(DOMAIN).decode()+'|fresh=1'),
    ('public-extension-denied', 14, 'denied-target', 'extension:denied:no-contact|fresh=1'),
)



def project(directory: Path) -> Path:
    app = published.project(directory, PRIVATE_NAME)
    source = read_file(ROOT / SOURCE)
    (app / 'src/main.ts').write_bytes(source)
    original = read_file(app / 'wit/world.wit')
    require(original.count(b'import latent:http/streaming@0.3.0;') == 1,
            'phase-fetch-original-world')
    wit = original.replace(b'import latent:http/streaming@0.3.0;',
                           b'import latent:http/phase-timing@0.4.0;')
    (app / 'wit/world.wit').write_bytes(wit)
    target = app / 'wit/deps/http-phases/package.wit'
    target.parent.mkdir(parents=True)
    target.write_bytes(read_file(app / 'vendor/lsf/wit/platform/http-phases/package.wit'))
    nominal = app / 'wit/deps/http-v3/package.wit'
    nominal.write_bytes(nominal_type_owner(read_file(nominal)))
    lock = json.loads(read_file(app / 'sdk-lock.json'))
    lock['template'] = {'name': 'typescript-phase-fetch', 'sourceDigest': digest(source),
                        'witDigest': digest(wit)}
    (app / 'sdk-lock.json').write_bytes((json.dumps(lock, indent=2)+'\n').encode())
    descriptor = app / 'capsule-project.json'
    manifest = json.loads(read_file(descriptor))
    require(manifest['limits']['cpuFuel'] == 1_000_000_000,
            'phase-fetch-original-fuel-profile')
    # One explicit initial application budget for every case and both tenants.
    # Host calls, helpers and continuations receive no independent allowance.
    manifest['limits']['cpuFuel'] = INITIAL_CPU_FUEL
    descriptor.write_bytes((json.dumps(manifest, indent=2)+'\n').encode())
    return app


def wire_prefix(raw: bytes, vector: str) -> bytes:
    """Change only two fixed status lines before the owned selector writes them."""
    choices = {'http-404': (b'HTTP/1.1 404 Fixture\r\n', b'HTTP/1.1 404 \r\n'),
               'http-500': (b'HTTP/1.1 500 Fixture\r\n', b'HTTP/1.1 500  Caf\xff \r\n')}
    if vector not in choices:
        return raw
    old, new = choices[vector]
    require(raw.startswith(old) and raw.count(old) == 1, 'phase-fetch-fixed-status-preimage')
    return new + raw[len(old):]


class PhasePeer(Peer):
    def _complete_request(self, stream, record):
        super()._complete_request(stream, record)
        record.output = wire_prefix(record.output, record.vector.identity)


def peer_evidence(value):
    validate(value)
    expected = [row[2] for row in VECTORS if row[1] not in (12, 14)] + ['pending-headers', 'partial-body', 'domain-json']
    require(value['state'] == 'stopped'
            and value['acceptedConnections'] == value['startedRequests'] == len(expected)
            and value['rejectedRequests'] == 0 and value['committedMutations'] == 1
            and [row['vector'] for row in value['requests']] == expected
            and all(row['role'] == 'primary' and row['state'] == 'closed'
                    and row['authorizationPresent'] is True for row in value['requests']),
            'phase-fetch-exact-peer-contacts')
    # Public abort rejects before the original I/O is released and completed;
    # the separate root cancellation/deadline gates are never released.
    contacts = [row for row in VECTORS if row[1] not in (12, 14)]
    released = [index+1 for index, row in enumerate(contacts) if row[1] == 9]
    require(value['completedResponseWrites'] == 11
            and [row['request'] for row in value['events'] if row['kind'] == 'gate-released'] == released,
            'phase-fetch-exact-public-abort-releases')
    mutation, = [row for row in value['requests'] if row['vector'] == 'commit-close']
    require(mutation['method'] == 'POST' and mutation['bodyBytes'] == 3
            and mutation['bodySha256'] == 'sha256:'+hashlib.sha256(b'one').hexdigest(),
            'phase-fetch-exact-single-mutation')
    return value
