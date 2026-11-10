"""One ordinary managed component with selected finite owner ceilings."""
import json
from tools.dotnet_standard_http_project import project as standard_project
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, digest, read_file

SOURCE = 'tools/fixtures/dotnet-managed-capacity/Main.cs'
REARM_SOURCE = 'tools/fixtures/dotnet-managed-capacity/TimerRearm.cs.in'
CASES = ('task-capacity', 'queue-capacity', 'timer-instance-capacity', 'periodic-timer',
    'disposed-before-dispatch', 'closing-required-timer', 'raw-native-ledger-capacity')
LIMITS = {'tasks': 8, 'executors': 2, 'queuedWork': 2, 'waits': 16,
    'timers': 8, 'results': 8, 'nativeOwners': 2}


def rearm_source(original, snippet):
    """Derive only the explicitly selected diagnostic from its frozen fixture."""
    require(type(original) is bytes and digest(original) ==
        'sha256:9ae5d864dd3a49d3dabff9c16e9751cc15f3e094a3e67a80a7b810d03279ae7c',
        'capacity-rearm-exact-original-fixture')
    require(type(snippet) is bytes and digest(snippet) == 'sha256:9f07f77ba9448db27020c269e09eeefcc3094d1e8e7381cc5a4817ac2163af73',
        'capacity-rearm-exact-reviewed-snippet')
    switch = b'        case 7: return await Fresh();\n'
    method = b'    private static async Task FreshTimer()\n'
    require(original.count(switch) == original.count(method) == 1,
        'capacity-rearm-exact-insertion-points')
    return original.replace(switch, switch + b'        case 8: return TimerRearmDiagnostic();\n', 1).replace(
        method, snippet + method, 1)


def project(directory, *, rearm_diagnostic=False):
    require(type(rearm_diagnostic) is bool, 'capacity-timer-rearm-selection')
    app = standard_project(directory)
    source = read_file(ROOT/SOURCE)
    if rearm_diagnostic:source = rearm_source(source, read_file(ROOT/REARM_SOURCE))
    (app/'src/Main.cs').write_bytes(source)
    lock = json.loads(read_file(app/'sdk-lock.json'))
    lock['template']['sourceDigest'] = digest(source)
    (app/'sdk-lock.json').write_text(json.dumps(lock, indent=2)+'\n', encoding='utf8', newline='\n')
    return app
