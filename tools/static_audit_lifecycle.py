"""Bounded real Linux node/CLI audit lifecycle campaign for signed static sites.

Called by the maintained static-site qualification after its other node exits.
This is a short controlled fixture, not a claimed multi-day production soak.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import time

from tools.phase2_operator_process import Client, Process, read_json, require, stopped_record, write_json
from tools.phase2_operator_scenario import NODE_ID, connect, stop
from tools.phase3_web_scenario import http_response
from tools.run_security_profile_workflow import replace_config

ROOT = Path(__file__).resolve().parents[1]
RECORDS = 32
DISK_BYTES = 1024 * 1024
MAX_COMMANDS = 384
MAX_SECONDS = 240


def digest(value):
    return 'sha256:' + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def record_inventory(root, cancellation, deadline):
    """Read only sealed/stopped fixture records; never edit journal internals."""
    result, total = {}, 0
    info = root.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o700, 'audit-fixture-record-directory')
    with os.scandir(root) as entries:
        for entry in entries:
            cancellation.check()
            require(time.monotonic() < deadline and len(result) < RECORDS, 'audit-fixture-scan-bound')
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
            descriptor = os.open(entry.path, flags)
            with os.fdopen(descriptor, 'rb') as stream:
                info = os.fstat(stream.fileno())
                require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
                        and stat.S_IMODE(info.st_mode) == 0o600 and 0 < info.st_size <= 16384,
                        'audit-fixture-private-record')
                raw = stream.read(16385)
                require(len(raw) == info.st_size and len(raw) <= 16384, 'audit-fixture-record-bound')
                total += len(raw)
                require(total <= DISK_BYTES, 'audit-fixture-record-byte-bound')
                result[entry.name] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    return dict(sorted(result.items()))


class CampaignClient(Client):
    def __init__(self, parent, directory, fixture):
        super().__init__(parent.executable, directory, parent.cancellation,
                         min(parent.deadline, time.monotonic() + MAX_SECONDS))
        self.fixture, self.trace, self.read_counts = fixture, [], {}

    def call(self, *arguments, **options):
        require(self.calls < MAX_COMMANDS, 'audit-fixture-command-bound')
        value = super().call(*arguments, **options)
        args = [str(argument) for argument in arguments]
        mutation = (args[:2] in [['web', 'publish'], ['web', 'renew-evidence'], ['trigger', 'apply']]
                    or args[:3] in [['audit', 'maintenance', 'rollover'], ['audit', 'maintenance', 'transfer']])
        if mutation:
            require(len(self.trace) < 64, 'audit-fixture-mutation-bound')
            receipt = value['data'].get('receipt') or value['data'].get('operation')
            self.trace.append({'argv': [argument.replace(str(self.directory.parent), '$WORK')
                .replace(str(self.fixture), '$FIXTURE') for argument in args],
                'exitStatus': self.last_exit_status, 'category': value['category'],
                'requestDispatched': value['requestDispatched'], 'outcomeKnown': value['outcomeKnown'],
                'receiptDigest': digest(receipt) if receipt else None,
                'auditAck': value['data'].get('auditAck'),
                'errorCode': value.get('error', {}).get('code') if value.get('error') else None})
        else:
            key = ' '.join(args[:3] if args[:1] == ['audit'] else args[:2])
            require(len(self.read_counts) < 16 or key in self.read_counts, 'audit-fixture-read-family-bound')
            self.read_counts[key] = self.read_counts.get(key, 0) + 1
        return value


class Campaign:
    def __init__(self, parent, args, directory, configure):
        self.args, self.directory = args, directory
        self.node_root, self.client_root = directory / 'node', directory / 'client'
        for path in (directory, self.node_root, self.client_root):
            path.mkdir(mode=0o700)
        self.client = CampaignClient(parent, self.client_root, args.fixture)
        self.config, self.hosts = configure(self.node_root, args.fixture)
        config = read_json(self.config)
        config['audit'] = {'mode': 'durable', 'records': RECORDS, 'diskBytes': DISK_BYTES,
                           'queuedOperations': 8, 'queryOwners': 2}
        config['supplyChain']['policyFile'] = 'audit-policy.json'
        config.pop('rollouts', None)
        replace_config(self.config, config)
        self.policy = read_json(args.fixture / 'audit-policy.json')
        require(self.policy['publisher']['maxProofAgeSeconds'] == 30
                and self.policy['builder']['maxProofAgeSeconds'] == 30, 'audit-fixture-freshness-profile')
        write_json(self.node_root / 'audit-policy.json', self.policy)
        self.root = self.node_root / 'data/audit'
        self.archives, self.external = directory / 'archives', directory / 'operator-custody'
        self.node, self.starts, self.sequence = None, 0, 0
        self.publication, self.package_digest = None, None
        self.epochs, self.shutdowns, self.renewals = [], [], []
        self.sample_files, self.archive_cursor = 0, None
        self.last_renewed_at = None

    def next_id(self, prefix):
        self.sequence += 1
        require(self.sequence <= 64, 'audit-fixture-operation-bound')
        return f'audit-fixture-{prefix}-{self.sequence}'

    @contextmanager
    def offline(self):
        config = self.client.config
        self.client.config = None
        try:
            yield
        finally:
            self.client.config = config

    def start(self):
        require(self.node is None and self.starts < 3, 'audit-fixture-start-bound')
        floor_path = self.node_root / 'data/supply-chain/floor.json'
        if floor_path.exists():
            floor = read_json(floor_path)['restartNotBefore']
            require(type(floor) is int and 0 < floor <= int(time.time()) + 6, 'audit-fixture-clock-floor')
            while int(time.time()) < floor:
                self.client.cancellation.check()
                require(time.monotonic() < self.client.deadline, 'audit-fixture-clock-deadline')
                time.sleep(0.05)
        self.starts += 1
        self.node = connect(self.client, self.args.node, self.node_root, self.config, 'tests', self.starts)
        require(read_json(self.node_root / 'audit-policy.json') == self.policy, 'audit-fixture-policy-changed')

    def shutdown(self):
        require(self.node is not None, 'audit-fixture-node-required')
        stop(self.client, self.node)
        self.shutdowns.append(stopped_record(self.node))
        self.node = None

    def sample(self):
        for _ in range(16):
            envelope = self.client.call('node', 'get', NODE_ID)
            topology = envelope['data']['inventory']['topology']
            rows = [row for row in topology['entries'] if row['name'] == 'audit-journal']
            require(topology['available'] and topology['complete'] and len(rows) == 1, 'audit-fixture-inventory')
            attributes = rows[0]['attributes']
            require(attributes['profile'] == 'audit-capacity-v1' and attributes['measurementStatus'] == 'available'
                    and attributes['maximumRecords'] == str(RECORDS)
                    and attributes['maximumDiskBytes'] == str(DISK_BYTES), 'audit-fixture-live-limits')
            require(attributes['audit_closed'] == '0' and attributes['audit_recovery_pending'] == '0',
                    'audit-fixture-owner-unhealthy')
            if all(attributes['audit_' + name] == '0' for name in
                   ('pending_attempts', 'queued_operations', 'queued_bytes', 'reserved_records', 'reserved_bytes')):
                return envelope, attributes
            self.client.cancellation.check()
            time.sleep(0.025)
        require(False, 'audit-fixture-owner-not-idle')

    def preflight(self, expected):
        envelope, _ = self.sample()
        self.sample_files += 1
        path = self.client_root / f'audit-inventory-{self.sample_files}.json'
        write_json(path, envelope)
        process = Process([str(self.args.node_js), str(ROOT / 'tools/static-release/audit-headroom.mjs'),
                           '--inventory', str(path), '--node', NODE_ID], ROOT, self.client.environment,
                          self.client.cancellation, maximum=16384)
        try:
            output = process.complete(min(self.client.deadline, time.monotonic() + 10))
            report = json.loads(output.stdout)
            require(report['schemaVersion'] == 'latent.static.audit-headroom.v1'
                    and report['status'] in expected and report['advisory'] is True
                    and report['reservation'] is False and report['budget']['criticalRecords'] == '6'
                    and report['budget']['bytes'] == '163840', 'audit-fixture-live-preflight')
            require(output.returncode == {'headroom-observed': 0, 'warning': 3, 'blocked': 4}[report['status']],
                    'audit-fixture-preflight-exit')
            return report
        finally:
            process.close()

    def publish(self):
        source = self.args.fixture / 'csr-a'
        result = self.client.call('web', 'publish', source / 'package', '--evidence', source / 'evidence/index.json',
                                  '--operation-id', self.next_id('publish'), '--expected-generation', '0')
        receipt = result['data']['operation']
        self.publication = receipt['publication']['id']
        self.package_digest = self.client.call('package', 'inspect', source / 'package')['data']['packageDigest']
        require(result['outcomeKnown'] and result['data']['auditAck']['status'] in
                ('durable', 'AUDIT_ACK_STATUS_DURABLE'), 'audit-fixture-publication-ack')
        self.last_renewed_at = time.monotonic()
        return receipt

    def renewal(self, rejected=False):
        original = self.client.call('web', 'get', '--publication', self.publication)['data']['record']
        operation = self.next_id('renew')
        result = self.client.call('web', 'renew-evidence', '--publication', self.publication,
            '--package-digest', self.package_digest, '--evidence', self.args.fixture / 'csr-a/evidence/index.json',
            '--operation-id', operation, '--expected-generation', original['generation'],
            codes=(4,) if rejected else (0,))
        if rejected:
            self.affirmative_rejection(result)
            after = self.client.call('web', 'get', '--publication', self.publication)['data']['record']
            require(after == original, 'audit-fixture-rejected-renewal-changed-state')
            return {'operationId': operation, 'publicationGenerationUnchanged': True,
                    'auditAck': result['data'].get('auditAck')}
        receipt = result['data']['operation']
        require(result['outcomeKnown'] and receipt['operationId'] == operation
                and receipt['resultingGeneration'] == str(int(original['generation']) + 1)
                and result['data']['auditAck']['status'] in ('durable', 'AUDIT_ACK_STATUS_DURABLE'),
                'audit-fixture-renewal-receipt')
        self.last_renewed_at = time.monotonic()
        self.renewals.append(receipt)
        return receipt

    @staticmethod
    def affirmative_rejection(result):
        require(result['category'] == 'platform-failure' and result['outcomeKnown'] is True
                and result['error']['code'] == 'resource-exhausted', 'audit-fixture-affirmative-rejection')
        reasons = [item.get('fields', {}).get('reason') for item in result['error'].get('details', [])
                   if item.get('kind') == 'audit-journal']
        require('audit-capacity' in reasons, 'audit-fixture-capacity-reason')

    def trigger(self, method, rejected=False):
        name = 'audit-' + method.lower()
        before = self.client.call('trigger', 'get', name, codes=(0, 6))['data']
        generation = before['trigger']['generation'] if before['trigger'] else '0'
        operation = self.next_id(method.lower())
        manifest = self.client_root / (operation + '.json')
        write_json(manifest, {'apiVersion': 'latent.dev/v1alpha1', 'kind': 'HttpTrigger',
            'metadata': {'name': name, 'tenant': 'tests'}, 'spec': {
                'target': {'kind': 'static-web', 'publication': self.publication}, 'configuration': {
                    'profile': 'static-site-v1', 'scheme': 'http', 'host': self.hosts['csr'],
                    'path': '/', 'pathMatch': 'prefix', 'method': method}}})
        result = self.client.call('trigger', 'apply', manifest, '--operation-id', operation,
            '--expected-generation', generation, '--expected-state-version', before['stateVersion'],
            codes=(4,) if rejected else (0,))
        if rejected:
            self.affirmative_rejection(result)
            after = self.client.call('trigger', 'get', name, codes=(0, 6))['data']
            require(after == before, 'audit-fixture-rejected-trigger-changed-state')
            return {'operationId': operation, 'expectedGeneration': generation,
                    'expectedStateVersion': before['stateVersion'], 'unchanged': True,
                    'auditAck': result['data'].get('auditAck')}
        receipt = result['data']['receipt']
        require(result['outcomeKnown'] and result['data']['durability'] == 'confirmed'
                and receipt['operationId'] == operation and receipt['expectedGeneration'] == generation
                and receipt['expectedStateVersion'] == before['stateVersion'], 'audit-fixture-trigger-receipt')
        return receipt

    def cycle(self):
        preflight = self.preflight(('headroom-observed', 'warning'))
        renewal = self.renewal()
        get, head = self.trigger('GET'), self.trigger('HEAD')
        body, _ = http_response(self.client, self.node, self.hosts['csr'], '/orders/42',
                                headers={'Accept': 'text/html'})
        require(body, 'audit-fixture-signed-content-missing')
        http_response(self.client, self.node, self.hosts['csr'], '/orders/42', method='HEAD',
                      headers={'Accept': 'text/html'})
        return {'renewal': renewal['operationId'], 'get': get['operationId'], 'head': head['operationId'],
                'bodyDigest': 'sha256:' + hashlib.sha256(body).hexdigest(), 'status': 200,
                'preflightHeadroom': preflight['headroom']}

    def exhaust(self):
        # Explicit native mutations deliberately demonstrate that a prior read
        # did not reserve later capacity. They never bypass native admission.
        for _ in range(RECORDS):
            _, counters = self.sample()
            remaining = RECORDS - int(counters['audit_retained_records'])
            if remaining < 4:
                break
            self.trigger('GET')
        require(2 <= remaining <= 3, 'audit-fixture-partial-boundary')
        get = self.trigger('GET')
        head = self.trigger('HEAD', rejected=True)
        _, counters = self.sample()
        if int(counters['audit_retained_records']) < RECORDS:
            self.renewal(rejected=True)
            _, counters = self.sample()
        require(counters['audit_retained_records'] == str(RECORDS)
                and int(counters['audit_retained_bytes']) < DISK_BYTES // 2, 'audit-fixture-record-exhaustion')
        space = os.statvfs(self.root)
        require(space.f_bavail * space.f_frsize > DISK_BYTES, 'audit-fixture-filesystem-spare-capacity')
        rejection = self.renewal(rejected=True)
        report = self.preflight(('blocked',))
        require('audit-record-headroom-insufficient' in report['reasons'], 'audit-fixture-full-preflight-reason')
        page = self.client.call('audit', 'query', '--scope', 'tenant', '--page-size', '1')['data']
        token = page['page']['nextPageToken']
        require(token, 'audit-fixture-live-cursor')
        return {'committedGet': get, 'rejectedHead': head, 'rejectedRenewal': rejection,
                'records': counters['audit_retained_records'], 'bytes': counters['audit_retained_bytes'],
                'spareFilesystemBytes': str(space.f_bavail * space.f_frsize), 'oldCursor': token}

    def expire(self):
        require(self.last_renewed_at is not None, 'audit-fixture-original-renewal-time')
        # Real wall clock and the unchanged 30-second verified-evidence policy.
        until = self.last_renewed_at + 33
        while time.monotonic() < until:
            self.client.cancellation.check()
            require(time.monotonic() < self.client.deadline, 'audit-fixture-expiry-deadline')
            time.sleep(max(0.0, min(0.1, until - time.monotonic())))
        # A stale positive proof is StateConflict in latent-signing, not an
        # expired signature (PermissionDenied). HTTP maps the former to 503.
        # Do not qualify an arbitrary 503 as freshness enforcement: demand the
        # exact native pre-audit preparation failure and unchanged route/epoch.
        _, audit_before = self.sample()
        before = self.client.call('trigger', 'get', 'audit-get')['data']
        operation = self.next_id('expired-probe')
        manifest = self.client_root / (operation + '.json')
        write_json(manifest, before['trigger']['manifest'])
        generation, version = before['trigger']['generation'], before['stateVersion']
        refused = self.client.call('trigger', 'apply', manifest, '--operation-id', operation,
            '--expected-generation', generation, '--expected-state-version', version, codes=(4,))
        reasons = [item.get('fields', {}).get('reason') for item in refused.get('error', {}).get('details', [])
                   if item.get('kind') == 'admission.currentness']
        require(refused['category'] == 'platform-failure' and refused['outcomeKnown'] is True
                and refused['error']['code'] == 'state-conflict' and reasons == ['signature-stale-proof']
                and refused['data'].get('auditAck') is None and refused['data'].get('receipt') is None,
                'audit-fixture-expiry-cause-not-established')
        require(self.client.call('trigger', 'get', 'audit-get')['data'] == before,
                'audit-fixture-expiry-probe-changed-route')
        _, audit_after = self.sample()
        require(all(audit_before[key] == audit_after[key] for key in
                    ('audit_next_sequence', 'audit_retained_records', 'audit_retained_bytes')),
                'audit-fixture-expiry-probe-changed-journal')
        for method in ('GET', 'HEAD'):
            body, _ = http_response(self.client, self.node, self.hosts['csr'], '/orders/42', method=method,
                                   headers={'Accept': 'text/html'}, expected=503)
            require(not body, 'audit-fixture-expired-content-served')
        return {'proofAgeSeconds': 30, 'GET': 503, 'HEAD': 503, 'clock': 'actual-system-clock',
                'reason': 'signature-stale-proof', 'platformCode': 'state-conflict',
                'probe': {'operationId': operation, 'expectedGeneration': generation,
                          'expectedStateVersion': version, 'outcomeKnown': True,
                          'routeUnchanged': True, 'journalUnchanged': True}}

    def seal(self, full):
        with self.offline():
            # A live physical node still owns the exact original journal lock.
            live = self.client.call('audit', 'maintenance', 'status', '--journal', self.root,
                                    '--local-operator', codes=(4,))
            require(live['category'] == 'platform-failure', 'audit-fixture-live-maintenance-admitted')
        self.shutdown()
        records = record_inventory(self.root / 'records', self.client.cancellation, self.client.deadline)
        require(len(records) == RECORDS, 'audit-fixture-sealed-record-count')
        with self.offline():
            status = self.client.call('audit', 'maintenance', 'status', '--journal', self.root,
                                      '--local-operator')['data']
            epoch, operation = status['epoch'], f'{self.starts:032x}'
            arguments = ['audit', 'maintenance', 'rollover', '--journal', self.root, '--archives', self.archives,
                         '--expected-epoch', epoch, '--operation-id', operation, '--local-operator']
            if not self.epochs:
                unavailable = self.directory / 'unavailable-archive'
                write_json(unavailable, {'not': 'a-directory'})
                bad = list(arguments)
                bad[bad.index('--archives') + 1] = unavailable
                refusal = self.client.call(*bad, codes=(4,))
                require(not refusal['outcomeKnown'], 'audit-fixture-maintenance-uncertainty')
                require(record_inventory(self.root / 'records', self.client.cancellation, self.client.deadline) == records,
                        'audit-fixture-unavailable-destination-lost-history')
            result = self.client.call(*arguments)['data']
            retry = self.client.call(*arguments)['data']
            require(result['durability'] == 'confirmed' and retry['alreadyCompleted'] is True
                    and result['receipt'] == retry['receipt'], 'audit-fixture-rollover-receipt')
            archive = self.archives / epoch
            require(record_inventory(archive / 'records', self.client.cancellation, self.client.deadline) == records,
                    'audit-fixture-record-bytes-changed')
            verified = self.client.call('audit', 'archive', 'verify', '--archive', archive, '--epoch', epoch,
                                        '--local-operator')['data']
            coverage = verified['archive']
            require(verified['verified'] and coverage['records'] == str(RECORDS)
                    and coverage['headDigest'] == status['headDigest'] and coverage['historyComplete'] is False,
                    'audit-fixture-seal-coverage')
            query = ['audit', 'archive', 'query', '--archive', archive, '--epoch', epoch,
                     '--scope', 'tenant', '--page-size', '1', '--local-operator']
            page = self.client.call('--tenant', 'tests', *query)['data']
            require(page['records'] and page['nextPageToken'], 'audit-fixture-archive-query')
            foreign = self.client.call('--tenant', 'another-tenant', *query)['data']
            require(not foreign['records'], 'audit-fixture-archive-scope-filter')
            if self.archive_cursor:
                denied = self.client.call('--tenant', 'tests', *query, '--page-token', self.archive_cursor, codes=(4,))
                require(denied['category'] == 'platform-failure', 'audit-fixture-cross-epoch-cursor')
            self.archive_cursor = page['nextPageToken']
            active = self.client.call('audit', 'maintenance', 'status', '--journal', self.root,
                                      '--local-operator')['data']
            require(active['retainedRecords'] == '0' and active['nextSequence'] == status['nextSequence']
                    and active['previousEpoch'] == epoch, 'audit-fixture-sequence-reset')
            self.epochs.append({'epoch': epoch, 'seal': coverage['sealDigest'],
                'retainedFloor': coverage['retainedFloor'], 'highWatermark': coverage['highWatermark'],
                'recordInventoryDigest': digest(records), 'recordBytes': coverage['recordBytes'],
                'previousSeal': coverage['predecessorSealDigest'], 'receipt': result['receipt']})
        self.start()
        recovered = self.client.call('trigger', 'operation', full['committedGet']['operationId'])
        require(recovered['outcomeKnown'] and recovered['data']['receipt'] == full['committedGet'],
                'audit-fixture-retained-receipt-authority')
        denied = self.client.call('audit', 'query', '--scope', 'tenant', '--page-size', '1',
                                 '--page-token', full['oldCursor'], codes=(4,))
        require(denied['category'] == 'platform-failure', 'audit-fixture-live-old-cursor')

    def transfer(self):
        self.shutdown()
        oldest = self.epochs[0]
        with self.offline():
            result = self.client.call('audit', 'maintenance', 'transfer', '--journal', self.root,
                '--archives', self.archives, '--destination', self.external, '--epoch', oldest['epoch'],
                '--expected-seal', oldest['seal'], '--operation-id', 'f' * 32, '--local-operator')['data']
            require(result['durability'] == 'confirmed' and result['receipt']['transferredThrough'] == oldest['highWatermark'],
                    'audit-fixture-transfer-receipt')
            require(not (self.archives / oldest['epoch']).exists(), 'audit-fixture-local-capacity-not-released')
            inventory = record_inventory(self.external / 'records', self.client.cancellation, self.client.deadline)
            require(digest(inventory) == oldest['recordInventoryDigest'], 'audit-fixture-external-bytes-changed')
            verified = self.client.call('audit', 'archive', 'verify', '--archive', self.external,
                '--epoch', oldest['epoch'], '--local-operator')['data']
            require(verified['archive']['sealDigest'] == oldest['seal'], 'audit-fixture-external-seal')
            custody = self.client.call('audit', 'maintenance', 'custody', '--archives', self.archives,
                '--journal-id', oldest['epoch'], '--local-operator')['data']
            require(len(custody['archives']) == 1 and custody['transferredThrough'] == oldest['highWatermark']
                    and custody['transferredHistoryAvailability'] == 'not-observed'
                    and custody['historyComplete'] is False, 'audit-fixture-custody-coverage')
            return {'receipt': result['receipt'], 'externalVerified': True,
                    'localArchives': len(custody['archives']), 'historyComplete': False}


def qualify(parent, args, directory, configure):
    started = time.monotonic()
    campaign = Campaign(parent, args, directory, configure)
    try:
        campaign.start()
        campaign.publish()
        cycles = [campaign.cycle(), campaign.cycle()]
        first = campaign.exhaust()
        expired = campaign.expire()
        campaign.seal(first)
        cycles.append(campaign.cycle())
        second = campaign.exhaust()
        campaign.seal(second)
        cycles.append(campaign.cycle())
        _, final = campaign.sample()
        require(int(final['audit_next_sequence']) > 2 * RECORDS + 1
                and campaign.epochs[1]['previousSeal'] == campaign.epochs[0]['seal'], 'audit-fixture-multiple-epochs')
        transfer = campaign.transfer()
        require(len(campaign.shutdowns) == 3 and campaign.starts == 3, 'audit-fixture-restart-count')
        require(len({cycle['bodyDigest'] for cycle in cycles}) == 1, 'audit-fixture-signed-content-changed')
        return {'schemaVersion': 'latent.static.audit-lifecycle.qualification.v1', 'passed': True,
            'profile': 'linux-signed-static-32-records-30-second-proof-age', 'multiDaySoak': False,
            'durationMillis': int((time.monotonic() - started) * 1000),
            'limits': {'recordsPerEpoch': RECORDS, 'diskBytes': DISK_BYTES, 'maximumCommands': MAX_COMMANDS,
                       'maximumSeconds': MAX_SECONDS, 'maximumStarts': 3, 'maximumSealedEpochs': 2},
            'cycles': cycles, 'epochs': campaign.epochs, 'expiryDenial': expired, 'transfer': transfer,
            'fullBoundaries': [{key: value for key, value in item.items() if key not in ('oldCursor', 'committedGet')}
                               for item in (first, second)],
            'commands': campaign.client.trace, 'readCommands': campaign.client.read_counts,
            'cliProcesses': campaign.client.calls, 'nextSequence': final['audit_next_sequence'],
            'shutdowns': campaign.shutdowns, 'receiptRecoveryWithoutReplay': True,
            'activeAndArchiveEpochCursorsRejectCrossing': True, 'acknowledgedRecordBytesPreserved': True,
            'historyComplete': False, 'policyUnchanged': True}
    finally:
        campaign.client.node = None
        if campaign.node is not None:
            campaign.node.close()
