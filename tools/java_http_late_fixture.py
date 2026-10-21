"""Ordinary cancellation/late-completion source; SDK observe is diagnostic only."""
import json
from pathlib import Path

from tools.java_http_phase_fixture import project as phase_project
from tools.rust_capsule_project import ROOT, digest, read_file, read_json

SOURCE = 'tools/fixtures/java-http-late-completion/Capsule.java'
CASES = ((0, 'cancelled-executor-future-late-http'), (2, 'fresh-after-executor'),
         (1, 'cancelled-default-completable-late-http'), (2, 'fresh-after-completable'))


def project(directory: Path) -> Path:
    app = phase_project(directory)
    source = read_file(ROOT/SOURCE)
    (app/'src/dev/latent/app/Capsule.java').write_bytes(source)
    lock = read_json(app/'sdk-lock.json')
    lock['template'] = {'name': 'java-http-late-completion-controls', 'sourceDigest': digest(source),
        'witDigest': digest(read_file(app/'wit/world.wit'))}
    (app/'sdk-lock.json').write_bytes((json.dumps(lock, indent=2)+'\n').encode())
    return app
