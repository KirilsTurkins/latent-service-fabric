"""Ordinary default HttpClient content and accepted managed work, with no handler injection."""
import json
from tools.dotnet_standard_http_project import project as standard_project
from tools.rust_capsule_project import ROOT, digest, read_file

SOURCE = 'tools/fixtures/dotnet-http-mixed/Main.cs'
CASES = (
    'explicit-unsupported-options', 'single-consumed-response-view', 'borrowed-output',
    'headers-read-task-context', 'content-read-incomplete', 'owned-stream-content',
    'incomplete-request-producer', 'declared-length-mismatch', 'request-limit',
    'pending-body-cancellation', 'early-response-disposal', 'root-return-accepted-http',
    'root-trap-accepted-http', 'late-completion-cancelled-result', 'reserved-cookie-header',
    'redirect-unfollowed', 'fresh-default-client', 'foreign-origin-refusal',
    'root-cancel-pending-body', 'root-deadline-pending-body',
)


def project(directory):
    app = standard_project(directory)
    source = read_file(ROOT/SOURCE)
    (app/'src/Main.cs').write_bytes(source)
    lock = json.loads(read_file(app/'sdk-lock.json'))
    lock['template']['sourceDigest'] = digest(source)
    (app/'sdk-lock.json').write_text(json.dumps(lock, indent=2)+'\n', encoding='utf8', newline='\n')
    return app
