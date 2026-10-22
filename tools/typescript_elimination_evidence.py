"""Finite compiler module-contribution witness, never arbitrary API reachability."""
from tools.phase2_operator_process import require
from tools.rust_capsule_project import digest
from tools.typescript_elimination_fixture import CALLBACK, LIBRARY

CALLBACK_PATH = 'dependencies/npm/node_modules/outside-elimination-callback/index.mjs'
LIBRARY_PATH = 'dependencies/npm/node_modules/outside-elimination-library/index.mjs'


def contribution(value, *, selected):
    require(type(selected) is bool and isinstance(value, dict), 'elimination-compiler-witness-shape')
    captured = value.get('capturedInputs')
    require(isinstance(captured, list) and 0 < len(captured) <= 8192,
        'elimination-bounded-compiler-captured-inputs')
    paths = [row.get('path') for row in captured if isinstance(row, dict)]
    require(len(paths) == len(captured) == len(set(paths)), 'elimination-unique-compiler-captured-inputs')
    for name, source in ((CALLBACK_PATH, CALLBACK), (LIBRARY_PATH, LIBRARY)):
        expected = {'path': name, 'digest': digest(source.encode()), 'size': len(source.encode())}
        require([row for row in captured if row.get('path') == name] == [expected],
            'elimination-exact-original-compiler-input')
        require(value['inputs'][name]['bytes'] == len(source.encode()), 'elimination-compiler-input-size')
    require(value.get('standardClockProfile') == 'lsf-standard-clock-unsupported-v1'
        and value.get('standardEntropyProfile') == 'lsf-math-random-unsupported-v1',
        'elimination-original-unselected-runtime-profiles')
    outputs = value.get('outputs')
    require(isinstance(outputs, dict) and 1 <= len(outputs) <= 4, 'elimination-bounded-compiler-outputs')
    modules = [row for row in outputs.values() if isinstance(row, dict) and row.get('entryPoint') == 'src/main.ts']
    require(len(modules) == 1, 'elimination-one-actual-application-bundle')
    bundle = modules[0]
    require(bundle.get('exports') == ['api'] and bundle.get('imports') == [],
        'elimination-original-export-and-no-ambient-import')
    rows = bundle.get('inputs')
    require(isinstance(rows, dict) and 1 <= len(rows) <= 8192, 'elimination-bounded-module-contributions')
    for name in (LIBRARY_PATH, 'src/main.ts'):
        require(type(rows[name]['bytesInOutput']) is int and 0 < rows[name]['bytesInOutput'] <= 32 * 1024**2,
            'elimination-positive-root-and-library-contributions')
    callback = rows.get(CALLBACK_PATH)
    count = 0 if callback is None else callback.get('bytesInOutput')
    require(type(count) is int and 0 <= count <= 32 * 1024**2 and (count > 0) is selected,
        'elimination-exact-callback-module-contribution')
    return {'rootEdgeSelected': selected, 'callbackSource': digest(CALLBACK.encode()),
        'librarySource': digest(LIBRARY.encode()), 'callbackBytesInBundle': count,
        'callbackModuleRetained': selected, 'scope': 'one-exact-esbuild-application-module',
        'fullComponentEngineApiAbsentClaimed': False, 'arbitraryApiClassification': 'unknown',
        'runtimeExecutionQualified': False}
