"""Real bounded TLS peer for the fixed upstream; observations contain no secrets."""
from __future__ import annotations

import secrets
import socket
import ssl
import threading
import time


class Peer:
    def __init__(self, directory):
        self.secret = 'Bearer ' + secrets.token_hex(32)
        self.mode = 'ok'
        self.requests = []
        self.closed_stalls = 0
        self.stop = threading.Event()
        self.accepted = threading.Event()
        self.failure = None
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 8443))
        self.listener.listen(2)
        self.listener.settimeout(0.1)
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.context.load_cert_chain(directory / 'server.pem', directory / 'server.key')
        self.worker = threading.Thread(target=self.run, name='static-api-tls-peer')
        self.worker.start()

    def run(self):
        try:
            while not self.stop.is_set():
                try:
                    raw, _ = self.listener.accept()
                except socket.timeout:
                    continue
                with raw:
                    raw.settimeout(2)
                    try:
                        with self.context.wrap_socket(raw, server_side=True) as stream:
                            data = b''
                            while b'\r\n\r\n' not in data and len(data) <= 8192:
                                part = stream.recv(1024)
                                if not part: break
                                data += part
                            if len(self.requests) >= 64 or len(data) > 8192:
                                raise RuntimeError('static-api-peer-request-bound')
                            lines = data.decode('ascii').split('\r\n')
                            headers = dict(line.lower().split(': ', 1) for line in lines[1:] if ': ' in line)
                            self.requests.append({'target': lines[0], 'credentialMatches':
                                headers.get('authorization') == self.secret.lower(),
                                'headerNames': sorted(headers), 'mode': self.mode})
                            self.accepted.set()
                            if self.mode == 'stall':
                                # Observe actual cancellation closing the provider socket.
                                deadline = time.monotonic() + 3
                                while not self.stop.is_set() and time.monotonic() < deadline:
                                    try:
                                        if stream.recv(1) == b'':
                                            self.closed_stalls += 1
                                            break
                                    except socket.timeout:
                                        continue
                                continue
                            status = {'ok': 200, 'error': 503, 'redirect': 302}[self.mode]
                            payload = b'private-upstream-response-must-not-reach-the-browser'
                            redirect = b'Location: https://other-customer.invalid/private\r\n' if status == 302 else b''
                            stream.sendall(b'HTTP/1.1 ' + str(status).encode() + b' Result\r\n' + redirect
                                + b'Content-Type: text/plain\r\nConnection: close\r\nContent-Length: '
                                + str(len(payload)).encode() + b'\r\n\r\n' + payload)
                    except (ssl.SSLError, ConnectionError, socket.timeout):
                        pass
        except BaseException as error:
            self.failure = type(error).__name__

    def close(self):
        self.stop.set()
        self.worker.join(4)
        self.listener.close()
        if self.worker.is_alive() or self.failure:
            raise RuntimeError('static-api-peer-owner-failed')
