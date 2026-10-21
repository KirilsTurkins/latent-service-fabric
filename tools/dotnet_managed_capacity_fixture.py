"""One ordinary managed component with selected finite owner ceilings."""
import json
from tools.dotnet_standard_http_project import project as standard_project
from tools.rust_capsule_project import ROOT, digest, read_file

SOURCE = 'tools/fixtures/dotnet-managed-capacity/Main.cs'
CASES = ('task-capacity', 'queue-capacity', 'timer-instance-capacity', 'periodic-timer',
    'disposed-before-dispatch', 'closing-required-timer', 'raw-native-ledger-capacity')
LIMITS = {'tasks': 8, 'executors': 2, 'queuedWork': 2, 'waits': 16,
    'timers': 8, 'results': 8, 'nativeOwners': 2}


def project(directory):
    app = standard_project(directory)
    source = read_file(ROOT/SOURCE)
    (app/'src/Main.cs').write_bytes(source)
    lock = json.loads(read_file(app/'sdk-lock.json'))
    lock['template']['sourceDigest'] = digest(source)
    (app/'sdk-lock.json').write_text(json.dumps(lock, indent=2)+'\n', encoding='utf8', newline='\n')
    return app
