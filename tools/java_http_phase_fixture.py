"""Source fixture only; actual phase/signed lifecycle qualification is separate."""
from __future__ import annotations

import json
from pathlib import Path
import socket

from tools.java_http_client import PHASE_PROFILE_ID
from tools.qualify_java_published_http import project as published_project
from tools.rust_capsule_project import ROOT, digest, read_file, read_json

SOURCE = 'tools/fixtures/java-http-phases/Capsule.java'
WORLD = 'tools/fixtures/java-http-phases/world.wit'
CASES = ('published-defaults', 'explicit-nonzero-success', 'headers-read-timeout',
    'body-read-timeout', 'root-deadline-is-not-phase-timeout', 'root-cancel-is-not-phase-timeout',
    'fresh-explicit-success', 'connect-timeout', 'connect-root-deadline', 'connect-root-cancel',
    'published-http-request-defaults')


class ConnectBacklog:
    """Linux fixture: fill one accept backlog without issuing any HTTP request."""
    def __init__(self):
        self.listener = None
        self.connections = []
        try:
            self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.listener.bind(('127.0.0.1', 0))
            self.listener.listen(1)
            self.address = self.listener.getsockname()
            for _ in range(2):
                owned = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.connections.append(owned)
                owned.settimeout(1)
                owned.connect(self.address)
        except BaseException:
            try:
                self.close()
            except Exception:
                pass
            raise

    def origin(self):
        if self.listener is None:
            raise ValueError('java-phase-connect-fixture-closed')
        return {'scheme': 'http', 'host': self.address[0], 'port': self.address[1]}

    def close(self):
        failure = None
        while self.connections:
            try:
                self.connections.pop().close()
            except OSError as error:
                failure = failure or error
        if self.listener is not None:
            try:
                self.listener.close()
            except OSError as error:
                failure = failure or error
            finally:
                self.listener = None
        if failure is not None:
            raise failure


def project(directory: Path) -> Path:
    app = published_project(directory)
    source, wit = read_file(ROOT/SOURCE), read_file(ROOT/WORLD)
    (app/'src/dev/latent/app/Capsule.java').write_bytes(source)
    (app/'wit/world.wit').write_bytes(wit)
    declaration = read_json(app/'java-dependencies.json')
    if declaration['dependencies'] != [{'exclusions': [], 'group': 'com.goebl',
            'name': 'david-webb', 'scope': 'runtime', 'version': '1.3.0'}]:
        raise ValueError('java-phase-published-dependency-preimage')
    declaration['dependencies'].append({'exclusions': [], 'group': 'com.github.kevinsawicki',
        'name': 'http-request', 'scope': 'runtime', 'version': '6.0'})
    (app/'java-dependencies.json').write_bytes((json.dumps(declaration, indent=2)+'\n').encode())
    descriptor = read_json(app/'capsule-project.json')
    descriptor['httpClient'] = {'profile': PHASE_PROFILE_ID}
    (app/'capsule-project.json').write_bytes((json.dumps(descriptor, indent=2)+'\n').encode())
    for package in ('http-v3', 'http-phases', 'activation-runtime'):
        relative = 'wit/platform/' + package + '/package.wit'
        target = app/'wit/deps'/package/'package.wit'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(read_file(app/'vendor/lsf'/relative))
    lock = read_json(app/'sdk-lock.json')
    lock['template'] = {'name': 'java-http-phase-controls', 'sourceDigest': digest(source),
        'witDigest': digest(wit)}
    (app/'sdk-lock.json').write_bytes((json.dumps(lock, indent=2)+'\n').encode())
    return app
