"""Current POST facts stay distinct from preserved PUT records and authority."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.java_transaction_qualification import current_recipient as current


class CurrentRecipient(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.root.chmod(0o700)
        self.declaration = current.endpoint({'scheme': 'https', 'host': 'localhost', 'port': 45123}, 'e' * 64)
        self.credential = b'Bearer synthetic-current-test-only'
        self.peer = current.Recipient(self.root, self.declaration, self.credential)
        self.key = 'lsf-effect-' + 'a' * 64
        self.body = b'ordinary synthetic bytes\0'
        self.digest = hashlib.sha256(self.body).hexdigest()
        self.headers = {'authorization': self.credential.decode(), 'content-type': 'application/octet-stream',
            'idempotency-key': self.key, 'lsf-endpoint-contract': current.CONTRACT,
            'lsf-endpoint-incarnation': self.declaration['endpointIncarnation'],
            'lsf-idempotency-retention-millis': str(current.RETENTION_MILLIS),
            'lsf-body-sha256': self.digest}

    def call(self, method='POST', path='/effect', body=None, headers=None):
        return self.peer.handle(method, path, self.headers if headers is None else headers,
                                self.body if body is None else body)

    def test_probe_and_absent_lookup_create_no_mutation(self):
        status, profile, lost = self.call('GET', body=b'')
        self.assertEqual(status, 200)
        self.assertEqual(profile['contract'], 'lsf-atomic-idempotent-http-v1')
        self.assertEqual(profile['retentionMillis'], 600000)
        self.assertEqual(profile['maximumPayloadBytes'], 27)
        self.assertFalse(lost)
        status, receipt, lost = self.call('GET', '/receipts/' + self.key, body=b'')
        self.assertEqual((status, receipt['outcome'], receipt['sequence'], receipt['duplicate']),
                         (404, 'absent', 0, False))
        self.assertEqual(self.peer.observation()['mutations'], 0)

    def test_original_post_and_lookup_preserve_exact_sequence_and_record(self):
        status, receipt, lost = self.call()
        self.assertEqual((status, receipt['sequence'], receipt['duplicate'], lost), (201, 1, False, False))
        path = self.root / (self.key + '.json')
        original = path.read_bytes()
        status, duplicate, _ = self.call()
        self.assertEqual((status, duplicate['sequence'], duplicate['duplicate']), (200, 1, True))
        status, found, _ = self.call('GET', '/receipts/' + self.key, body=b'')
        self.assertEqual((status, found['sequence'], found['bodyDigest']), (200, 1, self.digest))
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.peer.observation()['mutations'], 1)

    def test_changed_input_conflicts_without_rewriting_original_acceptance(self):
        self.call()
        path = self.root / (self.key + '.json')
        original = path.read_bytes()
        changed = b'changed bytes'
        headers = dict(self.headers, **{'lsf-body-sha256': hashlib.sha256(changed).hexdigest()})
        status, receipt, lost = self.call(body=changed, headers=headers)
        self.assertEqual((status, receipt['outcome'], receipt['sequence'], lost), (409, 'conflict', 0, False))
        self.assertEqual(receipt['bodyDigest'], self.digest)
        self.assertEqual(path.read_bytes(), original)

    def test_lost_reply_follows_durable_acceptance_and_restart_deduplicates(self):
        (self.root / 'mode').write_text('accept-disconnect', encoding='ascii')
        status, receipt, lost = self.call()
        self.assertEqual((status, receipt['sequence'], lost), (201, 1, True))
        self.peer = current.Recipient(self.root, self.declaration, self.credential)
        self.assertEqual(self.peer.observation()['originalRecords'], 1)
        status, receipt, lost = self.call()
        self.assertEqual((status, receipt['sequence'], receipt['duplicate'], lost), (200, 1, True, False))
        self.assertEqual(self.peer.observation()['mutations'], 1)

    def test_rejected_mutation_retains_no_acceptance_record(self):
        (self.root / 'mode').write_text('reject', encoding='ascii')
        status, receipt, lost = self.call()
        self.assertEqual((status, receipt['outcome'], receipt['sequence'], lost), (422, 'rejected', 0, False))
        self.assertEqual(self.peer.observation()['mutations'], 0)

    def test_put_old_keys_or_headers_and_wrong_credential_do_not_mutate(self):
        cases = [('PUT', self.headers), ('POST', dict(self.headers, **{'idempotency-key': 'a' * 64})),
                 ('POST', dict(self.headers, **{'lsf-endpoint-contract': 'latent.http-effect.put-once.v1'})),
                 ('POST', dict(self.headers, authorization='Bearer wrong'))]
        for method, headers in cases:
            with self.subTest(method=method, headers=set(headers)):
                self.assertIn(self.call(method, headers=headers)[0], {400, 403, 405, 421})
                self.assertEqual(self.peer.observation()['mutations'], 0)

    def test_tampered_retained_payload_or_sequence_is_refused(self):
        self.call()
        path = self.root / (self.key + '.json')
        original = path.read_bytes()
        row = json.loads(original)
        for name, value in (('payloadBase64', 'Y2hhbmdlZA=='), ('sequence', 2), ('formatVersion', True)):
            with self.subTest(field=name):
                path.write_text(json.dumps(dict(row, **{name: value})), encoding='utf-8')
                with self.assertRaises(ValueError):
                    current.Recipient(self.root, self.declaration, self.credential)
        path.write_bytes(original)

    def test_changed_declared_endpoint_cannot_reuse_recipient_installation(self):
        changed = current.endpoint(dict(self.declaration['origin'], port=45124), 'e' * 64)
        with self.assertRaisesRegex(ValueError, 'retained-endpoint'):
            current.Recipient(self.root, changed, self.credential)

    def test_record_ceiling_refuses_the_next_mutation_without_eviction(self):
        for ordinal in range(32):
            headers = dict(self.headers, **{'idempotency-key': 'lsf-effect-' + f'{ordinal:064x}'})
            self.assertEqual(self.call(headers=headers)[0], 201)
        headers = dict(self.headers, **{'idempotency-key': 'lsf-effect-' + 'f' * 64})
        with self.assertRaisesRegex(ValueError, 'record-count'):
            self.call(headers=headers)
        self.assertEqual(len(self.peer.records), 32)
        self.assertTrue((self.root / ('lsf-effect-' + '0' * 64 + '.json')).is_file())


if __name__ == '__main__':
    unittest.main()
