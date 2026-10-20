"""Real peer controls distinguish completed late responses from socket abandonment."""
from contextlib import closing
import copy
import json
from pathlib import Path
import socket
import tempfile
import time
import unittest
from urllib.parse import urlsplit
from unittest.mock import patch
from tools import typescript_fetch_late as late
from tools import qualify_typescript_fetch_late as qualification
from tools.phase2_operator_process import WorkflowError
from tools.standard_http.peer import Peer


class FetchLateTests(unittest.TestCase):
    def test_completed_provider_responses_and_real_gate_release_are_required(self):
        authorization=b'Bearer '+b'0'*64
        with closing(Peer(authorization,maximum_seconds=10)) as peer:
            for vector in late.VECTORS:
                address=urlsplit(peer.url(vector));expires=time.monotonic()+5
                with socket.create_connection((address.hostname,address.port),timeout=2) as client:
                    client.sendall(b'GET '+address.path.encode()+b' HTTP/1.1\r\nHost: '+address.netloc.encode()+b'\r\nAuthorization: '
                        +authorization+b'\r\nConnection: close\r\n\r\n')
                    client.setblocking(False);received=bytearray();released=False
                    while True:
                        self.assertLess(time.monotonic(),expires)
                        peer.poll(.001)
                        if peer.gates() and not released:
                            self.assertEqual(len(peer.gates()),1);peer.release(peer.gates()[0]);released=True
                        try:data=client.recv(8192)
                        except BlockingIOError:continue
                        if not data:break
                        received.extend(data);self.assertLess(len(received),65536)
                    self.assertTrue(released);self.assertTrue(received.startswith(b'HTTP/1.1 200'))
            peer.close();observed=peer.observation()
        self.assertEqual(late.peer_evidence(observed),observed)
        for field in ('startedRequests','acceptedConnections','completedResponseWrites','committedMutations'):
            invalid=copy.deepcopy(observed);invalid[field]+=1
            with self.subTest(field=field),self.assertRaises((WorkflowError,ValueError)):
                late.peer_evidence(invalid)
        invalid=copy.deepcopy(observed);invalid['requests'][0]['closeReason']='remote-write-half-ended'
        with self.assertRaises((WorkflowError,ValueError)):late.peer_evidence(invalid)

    def test_original_manifest_limits_and_exact_probe_source_remain_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);original=late.base.project(root/'original');actual=late.project(root/'actual')
            self.assertEqual((actual/'capsule-project.json').read_bytes(),(original/'capsule-project.json').read_bytes())
            self.assertEqual((actual/'src/main.ts').read_bytes(),(late.ROOT/late.SOURCE).read_bytes())
            self.assertEqual(json.loads((actual/'sdk-lock.json').read_bytes())['template']['sourceDigest'],
                late.digest((actual/'src/main.ts').read_bytes()))

    def test_compiler_failure_cannot_become_signed_runtime_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);native={name:root/name for name in late.base.PRODUCTS}
            for path in native.values():path.write_bytes(b'bounded-test-input')
            with patch.object(qualification,'native_inputs',return_value=(native,{'historical':True})), \
                    patch.object(qualification,'build',side_effect=ValueError('component-build-failed')), \
                    patch.object(qualification,'execute') as execute:
                with self.assertRaisesRegex(ValueError,'component-build-failed'):
                    qualification.qualify(root/'acquired',root/'tools',root/'output')
            execute.assert_not_called()


if __name__=='__main__':unittest.main()
