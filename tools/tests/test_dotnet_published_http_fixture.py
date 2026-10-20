"""Capture identities and immutable ordinary default-client project boundaries."""
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
import copy
import socket
import time
from urllib.parse import urlsplit
from unittest.mock import patch

from tools import dotnet_published_http_fixture as fixture
from tools.dotnet_guest.project import validate
from tools.dotnet_standard_http_project import project as original
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import snapshot


class PublishedHttpCapture(unittest.TestCase):
    def test_real_peer_oracle_requires_all_contacts_and_actual_uncertain_mutation(self):
        from tools import dotnet_published_http_node as node
        from tools.standard_http.peer import Peer
        from tools.standard_http.vectors import BY_ID
        secret = b'Bearer '+b'1'*64
        peer = Peer(secret, maximum_seconds=15)
        try:
            for vector in node.VECTORS:
                url = urlsplit(peer.url(vector))
                client = socket.create_connection((url.hostname,url.port),timeout=2)
                try:
                    mutation = vector in ('method-bytes','commit-close')
                    body = bytes((0,1,2,3)) if mutation else b''
                    client.sendall((b'POST' if mutation else b'GET')+b' '+url.path.encode()+b' HTTP/1.1\r\nHost: '
                        +url.netloc.encode()+b'\r\nAuthorization: '+secret+b'\r\nContent-Length: '
                        +str(len(body)).encode()+b'\r\n\r\n'+body)
                    client.setblocking(False)
                    expires = time.monotonic()+2
                    while True:
                        self.assertLess(time.monotonic(),expires)
                        peer.poll(.001)
                        try:chunk=client.recv(8192)
                        except BlockingIOError:chunk=None
                        if chunk==b'':break
                        if BY_ID[vector].gate and peer.gates():
                            if vector=='pending-headers' or peer.observation()['requests'][-1]['responseBytesWritten']>0:break
                finally:client.close()
                peer.poll(.001)
        finally:peer.close()
        observation=peer.observation()
        self.assertEqual(node.peer_result(observation)['contacts'],15)
        for mode in ('extra-contact','erased-mutation','released-gate','lost-credential'):
            changed=copy.deepcopy(observation)
            if mode=='extra-contact':changed['acceptedConnections']+=1
            elif mode=='erased-mutation':changed['committedMutations']=0
            elif mode=='released-gate':changed['events'].append({'sequence':len(changed['events'])+1,'kind':'gate-released','request':9})
            else:changed['requests'][0]['authorizationPresent']=False
            with self.assertRaises((WorkflowError,ValueError)):
                node.peer_result(changed)

    def test_normal_project_retains_original_sdk_limits_and_authoritative_wit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = original(root/'before')
            after = fixture.project(root/'after')
            a, b = snapshot(before), snapshot(after)
            validate(b)
            self.assertEqual({n:r for n,r in a.items() if n.startswith('vendor/')},
                             {n:r for n,r in b.items() if n.startswith('vendor/')})
            self.assertEqual(a['capsule-project.json'], b['capsule-project.json'])
            self.assertEqual(a['wit/world.wit'], b['wit/world.wit'])
            old, new = json.loads(a['sdk-lock.json']), json.loads(b['sdk-lock.json'])
            self.assertEqual(old['sdk'], new['sdk'])
            self.assertEqual(old['template']['witDigest'], new['template']['witDigest'])
            self.assertNotEqual(old['template']['sourceDigest'], new['template']['sourceDigest'])

    def test_private_coordinate_variation_preserves_exact_compiled_bytes(self):
        assembly = b'owned compiled bytes'
        rows = []
        for identity in ('Outside.Http.A.Alpha', 'Outside.Http.B.Delta'):
            raw = fixture.archive(identity, assembly)
            with zipfile.ZipFile(io.BytesIO(raw)) as package:
                self.assertEqual(package.testzip(), None)
                self.assertEqual(set(package.namelist()),
                                 {identity+'.nuspec','lib/net10.0/'+identity+'.dll'})
                self.assertEqual(package.read('lib/net10.0/'+identity+'.dll'), assembly)
                self.assertIn(('<id>'+identity+'</id>').encode(), package.read(identity+'.nuspec'))
                rows.append(raw)
        self.assertNotEqual(*rows)

    def test_private_archive_rejects_unsafe_coordinate_or_unbounded_material(self):
        for identity in ('../outside', '/outside', 'Outside/Foreign', 'Outside\nName'):
            with self.assertRaises(ValueError):
                fixture.archive(identity, b'compiled')
        for raw in (b'', bytearray(b'compiled'), b'x'*(4*1024**2+1)):
            with self.assertRaises(WorkflowError):
                fixture.archive('Outside.Http.Valid', raw)

    def test_malformed_analyzer_approval_refuses_before_staging_or_compiler_access(self):
        from tools import dotnet_catalogue_free_build as staging
        args = ['--project','unused','--output','unused','--tools','unused',
            '--contracts-tool','unused','--packager','unused','--repository','https://example.com/repo',
            '--expect-source-digest','sha256:'+'0'*64]
        for identity in ('moving-branch', 'sha256:'+'A'*64, 'sha256:'+'0'*63, ''):
            with patch.object(staging,'verify') as verify, patch.object(staging,'build') as build, \
                    self.assertRaisesRegex(WorkflowError,'executable-approval-identity'):
                staging.main(args+['--executable-approval',identity])
            verify.assert_not_called()
            build.assert_not_called()
