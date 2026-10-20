"""Optional public HttpRequest SPI fixture; ordinary default clients stay separate."""
from __future__ import annotations

import json
from pathlib import Path

from tools.java_http_phase_fixture import project as phase_project
from tools.rust_capsule_project import ROOT, digest, read_file, read_json

SOURCE = 'tools/fixtures/java-http-spi/Capsule.java'
WORLD = 'tools/fixtures/java-http-spi/world.wit'
CASES = ((0, 'public-spi-get'), (1, 'fresh-default-after-spi'),
         (2, 'spi-denied-target'), (3, 'spi-reserved-credential-header'),
         (4, 'public-spi-reset'), (1, 'fresh-default-after-errors'))


def project(directory: Path) -> Path:
    app = phase_project(directory)
    source, wit = read_file(ROOT/SOURCE), read_file(ROOT/WORLD)
    (app/'src/dev/latent/app/Capsule.java').write_bytes(source)
    (app/'wit/world.wit').write_bytes(wit)
    lock = read_json(app/'sdk-lock.json')
    lock['template'] = {'name': 'java-http-optional-public-spi',
        'sourceDigest': digest(source), 'witDigest': digest(wit)}
    (app/'sdk-lock.json').write_bytes((json.dumps(lock, indent=2)+'\n').encode())
    return app
