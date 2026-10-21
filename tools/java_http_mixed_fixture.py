"""Finite ordinary-client body fixture; no compiler eligibility exception."""
import json
from pathlib import Path

from tools.java_http_phase_fixture import project as phase_project
from tools.rust_capsule_project import ROOT, digest, read_file, read_json

SOURCE = 'tools/fixtures/java-http-mixed-bodies/Capsule.java'
CASES = ('consumed-response-views', 'borrowed-caller-output', 'held-body-sibling-and-backpressure',
    'retained-prefix-then-truncation', 'original-response-limit', 'exact-request-boundary',
    'original-request-limit', 'cancel-after-partial-body-and-sibling', 'fresh-after-cancel',
    'exact-response-boundary')


def project(directory: Path) -> Path:
    app = phase_project(directory)
    source = read_file(ROOT/SOURCE)
    (app/'src/dev/latent/app/Capsule.java').write_bytes(source)
    lock = read_json(app/'sdk-lock.json')
    lock['template'] = {'name': 'java-http-mixed-body-controls', 'sourceDigest': digest(source),
        'witDigest': digest(read_file(app/'wit/world.wit'))}
    # This is the compiler-owned project lock, not an accepted dependency lock.
    (app/'sdk-lock.json').write_bytes((json.dumps(lock, indent=2)+'\n').encode())
    return app
