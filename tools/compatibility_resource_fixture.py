"""Fixed ordinary resource cells; only original typed facts can qualify them.

No fixture installs a scheduler, counter, transport, diagnostic cause, quota or
GC hook. Node owners retain original grants, deadlines and physical teardown.
"""
from __future__ import annotations

from pathlib import Path

from tools.dev_workflow.common import require
from tools.rust_capsule_project import ROOT, digest, inventory, read_file, snapshot

# Both branches are compiler-visible actual core code. The recursive branch
# must trap with the engine's StackOverflow; generic Unreachable is not proof.
# The addition after call prevents a tail-call shape.
STACK_SOURCE = 'crates/latent-wasmtime/tests/fixtures/compatibility_stack.wat'
STACK_WAT = read_file(ROOT / STACK_SOURCE, 65536)
STACK_WIT = b'''package examples:compatibility-stack@1.0.0;
interface api { run: func(recurse: bool) -> u32; }
world service { export api; }
'''
STACK_CASES = (('overflow', True, 'original-engine-stack-overflow'),
               ('fresh-after-overflow', False, 42))

TYPESCRIPT_LIBRARY = b'''let calls = 0;
export async function resourceRuntime(mode) {
  if (++calls !== 1) throw new Error('compatibility-resource-state-not-fresh');
  if (mode === 'task-limit') {
    const pending = new Promise(() => {});
    const held = [];
    for (let index = 0; index < 64; ++index) {
      held.push(pending.then(() => { throw new Error('compatibility-pending-reaction-ran'); }));
    }
    throw new Error('compatibility-task-limit-not-refused');
  }
  if (mode === 'timer-limit') {
    const held = [];
    for (let index = 0; index < 64; ++index) {
      held.push(setTimeout(() => { throw new Error('compatibility-long-timer-ran'); }, 3600000));
    }
    throw new Error('compatibility-timer-limit-not-refused');
  }
  if (mode !== 'fresh' && mode !== 'parallel') throw new Error('compatibility-resource-mode');
  return 'compatibility-resource|fresh=1';
}
'''
TYPESCRIPT_CASES = (('task-limit', 'tasks', 16, 17), ('fresh', None, None, None),
    ('timer-limit', 'timers', 8, 9), ('fresh', None, None, None))


def stack(directory: Path):
    require(not directory.exists() and not directory.is_symlink(), 'compatibility-resource-fresh-stack-directory')
    directory.mkdir(mode=0o700)
    (directory / 'component.wat').write_bytes(STACK_WAT)
    (directory / 'world.wit').write_bytes(STACK_WIT)
    return {'wat': directory / 'component.wat', 'wit': directory / 'world.wit',
        'sourceDigest': digest(inventory(snapshot(directory))), 'engineTrapRequired': 'StackOverflow',
        'apiCauseFromUnreachable': False, 'originalBudgetsRequired': True, 'signedExecution': 'pending'}


def typescript(directory: Path, outside: Path):
    from tools import typescript_resource_runtime_fixture as original
    app, record = original.project(directory, outside)
    (outside / 'library/index.mjs').write_bytes(TYPESCRIPT_LIBRARY)
    return app, {**record, 'outside': digest(inventory(snapshot(outside))),
        'cases': [list(row) for row in TYPESCRIPT_CASES],
        'taskAdmission': 'original-intrinsic-reaction-before-allocation',
        'timerAdmission': 'original-timer-start-before-publication',
        'typedRefusalRequired': True, 'physicalRetirement': 'unproven'}


def go(directory: Path, outside: Path):
    from tools import go_resource_runtime_fixture as original
    from tools.go_guest.queues import PROFILE
    # Reuse the exact normal managed queue profile and original eight prepaid
    # slots. The existing 8/9 differential remains the component oracle; the
    # new qualifier additionally requires its original typed queue fact.
    return original.project(directory, outside, runtime_profile=PROFILE)


TYPESCRIPT_INITIALIZER = b'''
let compatibilityInitializerCalls = 0;
let compatibilityGreetingCalls = 0;
function compatibilityInitialization() {
  if (++compatibilityGreetingCalls !== 1) throw new Error('initializer-store-not-fresh');
  // Defining the class INSIDE the invoked function performs language-native
  // static initialization now, not during componentization/module snapshot.
  class Initializer {
    static value = (() => {
      if (++compatibilityInitializerCalls !== 1) throw new Error('initializer-repeated');
      const native = fallbackCase('catch:7');
      if (native !== 'fallback|typescript|unsupported|seed=7|alternate=42|fresh=1')
        throw new Error('initializer-wrong-native-refusal');
      return 42;
    })();
  }
  const first = Initializer.value, second = Initializer.value;
  if (first !== 42 || second !== 42 || compatibilityInitializerCalls !== 1)
    throw new Error('initializer-native-result-or-count');
  return {ok: 'api|typescript|initialization|unsupported|result=42|count=1'};
}
'''


def typescript_initializer(app: Path, capture: dict):
    """App-only source proposal; caller already used the normal SYNC capture.

    Both original fallback libraries remain byte-identical and accepted. This
    is class-static initialization during invocation, not component-start.
    """
    from tools.application_dependencies import verify_inputs
    from tools.typescript_guest.runtime_profile import SYNC_PROFILE
    before = snapshot(app)
    require(capture.get('language') == 'typescript' and capture.get('clockProfileEnabled') is False
        and capture.get('compilerExecuted') is False and digest(inventory(before)) == capture['sourceDigest'],
        'compatibility-initializer-original-SYNC-source-capture')
    accepted = verify_inputs(app, 'typescript')
    require(accepted is not None and accepted.lock['selection']['runtimeProfile'] == SYNC_PROFILE,
        'compatibility-initializer-original-SYNC-profile')
    source = before['src/main.ts']; anchor = b'  greet(name) {'
    require(source.startswith(b"import {fallbackCase} from 'outside-fallback-library';\n")
        and source.count(anchor) == 1, 'compatibility-initializer-original-greeting')
    selected = TYPESCRIPT_INITIALIZER + source.replace(anchor,
        anchor + b"\n    if (name === 'probe') return compatibilityInitialization();", 1)
    (app / 'src/main.ts').write_bytes(selected)
    after = snapshot(app)
    require(set(after) == set(before) and all(after[p] == raw for p, raw in before.items() if p != 'src/main.ts')
        and verify_inputs(app, 'typescript').identity == accepted.identity,
        'compatibility-initializer-app-only-original-libraries')
    return {'initializationKind': 'class-static-during-invocation',
        'expectedScope': 'reached-unsupported-during-initialization/fallback',
        'expectedResult': [{'ok': 'api|typescript|initialization|unsupported|result=42|count=1'}],
        'acceptedInputIdentity': accepted.identity, 'componentStartClaimed': False,
        'initializerExpectedCount': 1, 'runtimeQualified': False}
