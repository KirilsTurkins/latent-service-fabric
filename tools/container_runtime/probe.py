"""Private, bounded HTTP projection of authenticated node and HTTP-owner readiness."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import signal
import socket
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, '/opt/lsf/runtime')
from native_runtime import files
from native_runtime.common import InstallError, document, execute, require

BIND = ('127.0.0.1', 18181)
AUTHORITY = '127.0.0.1:18181'
CLIENT = Path('/etc/lsf/client.json')
CLI = '/opt/lsf/release/bin/latent'
MAX_AGE = 3.0


def observe(node_id: str) -> tuple[bool, bool]:
    started = time.monotonic()
    status, raw = execute([CLI, '--config', str(CLIENT), '--output', 'json',
        '--connect-timeout-ms', '250', '--rpc-timeout-ms', '1000', 'node', 'get', node_id],
        timeout=1.5, maximum=262144, stdout_only=True)
    require(status == 0 and time.monotonic() - started < 1.5, 'probe-node-unavailable')
    result = document(raw, 262144)
    require(result.get('schemaVersion') == 'latent.cli.result.v1' and result.get('category') == 'success'
            and result.get('outcomeKnown') is True, 'probe-observation-not-authoritative')
    inventory = result['data']['inventory']
    require(inventory['node']['id'] == node_id, 'probe-wrong-node')
    require(abs(time.time() * 1000 - int(inventory['observedAtUnixMillis'])) <= 3000, 'probe-observation-stale')
    topology = inventory['topology']
    require(topology['available'] is True and topology['complete'] is True, 'probe-http-owners-unavailable')
    rows = {}
    for row in topology['entries']:
        require(row['name'] not in rows, 'probe-duplicate-owner')
        rows[row['name']] = row
    for name in ('http-listener', 'http-owner'):
        row = rows[name]
        require(int(row['configuredCount']) == 1 and int(row['activeCount']) == 1, 'probe-http-owner-unavailable')
    spare = True
    for name in ('http-connections', 'http-exchanges', 'http-buffer-reservations'):
        row = rows[name]
        active, maximum = int(row['activeCount']), int(row['configuredCount'])
        require(0 <= active <= maximum and maximum > 0, 'probe-http-capacity-unavailable')
        spare &= active < maximum
    health = inventory['health']
    live = health['healthy'] is True
    # Conservatively retain native activation readiness, and ALSO require actual
    # complete HTTP owners/capacity and current pressure. No application is called.
    ready = live and health['ready'] is True and inventory['pressure']['loadAvailable'] is True and spare
    return live, ready


class Projection:
    def __init__(self):
        self.lock = threading.Lock()
        self.timestamp = 0.0
        self.live = False
        self.ready = False
        self.started = False

    def update(self, live, ready):
        with self.lock:
            self.timestamp = time.monotonic()
            self.live, self.ready = live, ready
            self.started |= ready

    def status(self, path):
        with self.lock:
            current = 0 <= time.monotonic() - self.timestamp <= MAX_AGE
            return current and {'/startup': self.started and self.live, '/live': self.live, '/ready': self.ready}[path]


def sample(projection, stopped, node_id):
    while not stopped.is_set():
        try:
            live, ready = observe(node_id)
        except Exception:
            live, ready = False, False
        projection.update(live, ready)
        if stopped.wait(1):
            break
    projection.update(False, False)


def request(connection, peer, projection, stopped):
    deadline = time.monotonic() + 0.5
    raw = bytearray()
    try:
        while b'\r\n\r\n' not in raw:
            remaining = deadline - time.monotonic()
            require(remaining > 0 and len(raw) < 4096, 'probe-request-bound')
            connection.settimeout(remaining)
            block = connection.recv(4096 - len(raw))
            require(block, 'probe-incomplete-request')
            raw.extend(block)
        head, body = bytes(raw).split(b'\r\n\r\n', 1)
        lines = head.decode('ascii').split('\r\n')
        method, path, version = lines[0].split(' ')
        require(len(lines) <= 17 and not body and version == 'HTTP/1.1', 'probe-request-shape')
        headers = {}
        for line in lines[1:]:
            name, value = line.split(':', 1)
            name = name.lower()
            require(name not in headers and name in {'host', 'connection', 'user-agent', 'accept', 'accept-encoding', 'content-length'},
                    'probe-unexpected-header')
            headers[name] = value.strip()
        require(peer[0] == BIND[0] and headers.get('host') == AUTHORITY
                and headers.get('content-length', '0') == '0', 'probe-exact-private-authority-required')
        if method not in {'GET', 'HEAD'}:
            code, value = 405, 'method-not-allowed'
        elif path not in {'/startup', '/live', '/ready'}:
            code, value = 404, 'not-found'
        elif not stopped.is_set() and projection.status(path):
            code, value = 200, 'ok'
        else:
            code, value = 503, 'unavailable'
    except Exception:
        code, value, method = 400, 'invalid-request', 'GET'
    payload = json.dumps({'status': value}, separators=(',', ':')).encode()
    reason = {200: 'OK', 400: 'Bad Request', 404: 'Not Found', 405: 'Method Not Allowed', 503: 'Service Unavailable'}[code]
    response = (f'HTTP/1.1 {code} {reason}\r\nContent-Type: application/json\r\n'
                f'Content-Length: {len(payload)}\r\nCache-Control: no-store\r\n'
                'X-Content-Type-Options: nosniff\r\nConnection: close\r\n\r\n').encode()
    connection.settimeout(0.5)
    try:
        connection.sendall(response + (b'' if method == 'HEAD' else payload))
    except OSError:
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node-id', required=True)
    parser.add_argument('--check', action='store_true', help='perform one private observation and exit')
    args = parser.parse_args()
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,127}', args.node_id), 'probe-node-id')
    # Credential bytes stay in the existing private file and the CLI process.
    with files.regular(CLIENT, 65536, owners={0, 10001}, private=True, trusted_gid=10001):
        pass
    if args.check:
        try:
            live, ready = observe(args.node_id)
            print(json.dumps({'live': live, 'ready': ready}))
        except (InstallError, KeyError) as error:
            print(json.dumps({'live': False, 'ready': False, 'reason': str(error)}))
        return
    projection, stopped = Projection(), threading.Event()
    for event in (signal.SIGTERM, signal.SIGINT):
        signal.signal(event, lambda *_: stopped.set())
    worker = threading.Thread(target=sample, args=(projection, stopped, args.node_id), name='lsf-probe-sample')
    worker.start()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(BIND)
            listener.listen(2)
            listener.settimeout(0.2)
            while not stopped.is_set():
                try:
                    connection, peer = listener.accept()
                except TimeoutError:
                    continue
                with connection:
                    request(connection, peer, projection, stopped)
    finally:
        stopped.set()
        worker.join(timeout=3)
        require(not worker.is_alive(), 'probe-worker-not-stopped')


if __name__ == '__main__':
    main()
