"""Exercise the actual owned TLS peer subprocess without an SDK/native build."""
from __future__ import annotations

import json
from pathlib import Path
import socket
import ssl
import tempfile
import time
import sys

from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import Process, require
from tools.rust_capsule_project import ROOT
from tools.standard_http.tls_peer import validate_tls
from tools.standard_http.vectors import DOMAIN, json_bytes

CASES = ('process-tls12-json', 'process-tls13-json', 'process-hostname-refused')


def exercise(certificate: Path, key: Path):
    with tempfile.TemporaryDirectory(prefix='lsf-tls-process-') as temporary, owned_cancellation() as cancellation:
        private = Path(temporary)
        credential = private/'authorization'
        authorization = b'Bearer '+b'p'*64
        credential.write_bytes(authorization)
        credential.chmod(0o600)
        process = Process([sys.executable, '-B', str(ROOT/'tools/standard_http/process_peer.py'),
            '--credential', str(credential), '--certificate', str(certificate), '--private-key', str(key)],
            private, build_environment(private), cancellation, maximum=65536)
        results = []
        try:
            startup = process.line(time.monotonic()+10)
            require(set(startup) == {'destinations', 'origins'}
                and set(startup['origins']) == {'primary', 'secondary'}
                and all(row['scheme'] == 'https' and row['host'] == '127.0.0.1'
                        for row in startup['origins'].values()), 'tls-process-public-startup')
            origin = startup['origins']['primary']
            for case in CASES:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                context.load_verify_locations(str(certificate))
                context.set_alpn_protocols(['http/1.1'])
                version = ssl.TLSVersion.TLSv1_2 if case == CASES[0] else ssl.TLSVersion.TLSv1_3
                context.minimum_version = context.maximum_version = version
                refused, response = False, bytearray()
                with socket.create_connection((origin['host'], origin['port']), timeout=3) as raw:
                    try:
                        with context.wrap_socket(raw, server_hostname=(
                                'wrong.invalid' if case == CASES[2] else '127.0.0.1')) as stream:
                            stream.sendall(b'GET /conformance/json HTTP/1.1\r\nHost: 127.0.0.1:'
                                +str(origin['port']).encode()+b'\r\nAuthorization: '+authorization
                                +b'\r\nConnection: close\r\n\r\n')
                            while True:
                                data = stream.recv(4096)
                                if not data:break
                                response.extend(data)
                                require(len(response)<=65536,'tls-process-response-bound')
                    except ssl.SSLCertVerificationError:
                        refused = True
                require(refused == (case == CASES[2]), 'tls-process-required-name-check')
                if not refused:
                    require(response.split(b'\r\n\r\n',1)[1] == json_bytes(DOMAIN),
                            'tls-process-actual-parsed-domain')
                results.append({'case':case,'certificateRejected':refused,'responseBytes':len(response)})
            process.stop()
            observation = json.loads(bytes(process.buffers[0]))
            validate_tls(observation)
            require(observation['failure'] is None and observation['state']=='stopped'
                and observation['acceptedConnections']==3 and observation['startedRequests']==2
                and observation['completedResponseWrites']==2 and observation['openConnections']==0
                and observation['listeningOrigins']==0 and observation['rejectedRequests']==0
                and len(observation['requests'])==3,'tls-process-exact-transport-retirement')
            require(all(row['authorizationPresent'] is True for row in observation['requests']
                if row.get('vector')=='domain-json')
                and sum(row['tls']['state']=='handshake-failed' for row in observation['requests'])==1,
                'tls-process-no-http-before-valid-name')
            require(process.closed and process.owner.finished and process.owner.process.returncode==0,
                    'tls-process-owned-group-reaped')
            public = {'cases':results,'peer':observation,'process':{'reaped':True,'exitCode':0},
                'signedGuestExecuted':False,'providerAccountingQualified':False,'privateKeyRetained':False}
            encoded = json.dumps(public)
            require(authorization.decode() not in encoded and str(key) not in encoded
                and 'PRIVATE KEY' not in encoded,'tls-process-public-receipt-only')
            return public
        finally:
            process.close()
