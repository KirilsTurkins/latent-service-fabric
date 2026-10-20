"""Actual loopback TLS fixture controls; these execute no SDK guest/provider."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import socket
import ssl
import time

from tools.standard_http.protocol import require
from tools.standard_http.tls_peer import TLSPeer, validate_tls
from tools.standard_http.vectors import DOMAIN, json_bytes

CASES = ('tls12-json', 'tls13-json', 'hostname-refused', 'trust-refused',
         'stalled-handshake-retired', 'early-tls-body-close')


def exercise(certificate: Path, private_key: Path) -> list[dict]:
    results = []
    for mode in CASES:
        expires = time.monotonic()+5
        polls = 0
        clock = [time.monotonic()]
        authorization = b'Bearer '+b'a'*64
        peer = TLSPeer(authorization, certificate, private_key, maximum_seconds=15,
                       **({'clock': lambda: clock[0]} if mode == 'stalled-handshake-retired' else {}))
        client = None
        response = bytearray()
        refused = False

        def progress():
            nonlocal polls
            polls += 1
            require(polls <= 2048 and time.monotonic() < expires, 'tls-reference-progress-bound')
            peer.poll(.002)

        try:
            raw = socket.create_connection(('127.0.0.1', peer.ports['primary']), timeout=1)
            if mode == 'stalled-handshake-retired':
                client = raw
                progress()
                require(len(peer.clients) == 1 and peer.started == 0, 'tls-reference-pending-handshake')
                clock[0] += 6
                peer.tick()
                require(not peer.clients and peer.rows[0]['closeReason'] == 'peer-request-deadline',
                        'tls-reference-original-handshake-deadline')
            else:
                raw.setblocking(False)
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                context.maximum_version = ssl.TLSVersion.TLSv1_3
                context.set_alpn_protocols(['http/1.1'])
                if mode != 'trust-refused':
                    context.load_verify_locations(str(certificate))
                if mode in {'tls12-json', 'tls13-json'}:
                    selected = ssl.TLSVersion.TLSv1_2 if mode == 'tls12-json' else ssl.TLSVersion.TLSv1_3
                    context.minimum_version = context.maximum_version = selected
                try:
                    client = context.wrap_socket(raw, server_hostname=(
                        'wrong.invalid' if mode == 'hostname-refused' else '127.0.0.1'),
                        do_handshake_on_connect=False)
                except BaseException:
                    raw.close()
                    raise
                while True:
                    progress()
                    try:
                        client.do_handshake()
                        break
                    except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
                        continue
                    except ssl.SSLCertVerificationError:
                        refused = True
                        break
                if mode in {'hostname-refused', 'trust-refused'}:
                    require(refused, 'tls-reference-required-certificate-refusal')
                    client.close()
                    while peer.clients:
                        progress()
                    require(peer.started == peer.completed == 0, 'tls-reference-no-http-before-trust')
                else:
                    require(not refused, 'tls-reference-trusted-handshake')
                    path = b'/conformance/body/partial' if mode == 'early-tls-body-close' else b'/conformance/json'
                    request = (b'GET '+path+b' HTTP/1.1\r\nHost: 127.0.0.1:'
                        + str(peer.ports['primary']).encode()+b'\r\nAuthorization: '
                        + authorization+b'\r\nConnection: close\r\n\r\n')
                    offset = 0
                    while offset < len(request):
                        progress()
                        try:
                            offset += client.send(request[offset:])
                        except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
                            continue
                    while True:
                        progress()
                        try:
                            chunk = client.recv(4096)
                        except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
                            continue
                        if not chunk:
                            require(mode != 'early-tls-body-close', 'tls-reference-body-was-not-held')
                            break
                        response.extend(chunk)
                        require(len(response) <= 65536, 'tls-reference-response-bound')
                        if mode == 'early-tls-body-close' and peer.gates():
                            require(len(peer.gates()) == 1 and peer.completed == 0,
                                    'tls-reference-original-body-gate')
                            client.close()
                            while peer.clients:
                                progress()
                            break
                    if mode != 'early-tls-body-close':
                        require(response.split(b'\r\n\r\n', 1)[1] == json_bytes(DOMAIN),
                                'tls-reference-real-parsed-http-body')
                    require(peer.started == 1 and not peer.clients, 'tls-reference-original-owner-retired')
        finally:
            if client is not None:
                client.close()
            observation = peer.close()
        validate_tls(observation)
        require(observation['acceptedConnections'] == 1 and observation['openConnections'] == 0
                and observation['connectionBoundRejections'] == observation['rejectedRequests'] == 0
                and authorization.decode() not in json.dumps(observation), 'tls-reference-exact-contact-and-secrets')
        results.append({'case':mode, 'certificateRejected':refused,
            'response':{'bytes':len(response),'sha256':'sha256:'+hashlib.sha256(response).hexdigest()},
            'peer':observation})
    require([row['case'] for row in results] == list(CASES), 'tls-reference-exact-cases')
    return results
