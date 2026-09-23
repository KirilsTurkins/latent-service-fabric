"""One-use reviewed feature-branch integration; removed before source capture."""
from pathlib import Path
import copy
import json

ROOT = Path(__file__).resolve().parents[2]


def replace(name, old, new):
    path = ROOT / name
    text = path.read_text()
    assert text.count(old) == 1, (name, old)
    path.write_text(text.replace(old, new))


def write(name, content):
    path = ROOT / name
    assert not path.exists(), name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


write('sdk/c-guest/tests/containment/c-project.json', json.dumps({
    'formatVersion': 1, 'name': 'containment', 'version': '1.0.0',
    'world': 'examples:containment/component@1.0.0', 'sources': ['component.c'],
    'memoryBytes': 4194304, 'sourceRepository': 'https://github.com/KirilsTurkins/latent-service-fabric'}, indent=2) + '\n')
write('sdk/c-guest/tests/containment/wit/world.wit', '''package examples:containment@1.0.0;
interface api { run: func(which: u32) -> u32; }
world component { export api; }
''')
write('sdk/c-guest/tests/containment/component.c', '''/* SPDX-License-Identifier: Apache-2.0 */
/* Executed qualification only: never installed as a teaching template. */
#include "lsf/guest.h"

static uint32_t activation_counter;

uint32_t exports_examples_containment_api_run(uint32_t which) {
    if (which == 0) return ++activation_counter;
    if (which == 1) __builtin_trap();
    if (which == 2) {
        /* Every allocation remains live until the real activation is torn
         * down. Volatile writes keep this an actual linear-memory workload. */
        for (;;) {
            volatile uint8_t *bytes = calloc(65536, 1);
            if (!bytes) __builtin_trap();
            for (size_t i = 0; i < 65536; i += 4096) bytes[i] = 1;
            __asm__ volatile("" : : "r"(bytes) : "memory");
        }
    }
    lsf_require(which == 3);
    for (;;) __asm__ volatile("" ::: "memory");
}
''')
replace('tools/c_guest/qualify.py', "    result = {'formatVersion': 1, 'nativeOwnership': 'passed', 'projects': receipts}", '''    name = 'containment'
    project = output / ('project-' + name)
    project.mkdir()
    for relative in ('component.c', 'c-project.json', 'wit/world.wit'):
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SDK / 'tests/containment' / relative, target)
    actual = bindings(project, output / ('lock-' + name), update=True)
    check_lock(SDK / 'tests/containment/c-bindings.lock.json', actual, update=update)
    receipts[name] = build(project, output / ('build-' + name))
    result = {'formatVersion': 1, 'nativeOwnership': 'passed', 'projects': receipts}''')
replace('crates/latent-wasmtime/tests/c_guest_authoring.rs',
        'for name in ["greeting", "word-count", "shipping"] {',
        'for name in ["greeting", "word-count", "shipping", "containment"] {')
# The real host wall deadline is also below the configured 100M fuel bound for
# the spin case; both are enforced by the ordinary deployed activation profile.
replace('crates/latent-wasmtime/tests/c_guest_authoring.rs',
        'deployment["spec"]["resources"]["wallTimeLimitMillis"] = json!(5000);',
        'deployment["spec"]["resources"]["wallTimeLimitMillis"] = json!(if name == "containment" { 20 } else { 5000 });')
replace('tools/c_guest/node.py', "    if name == 'greeting':", "    if name == 'containment':\n        return [1]\n    if name == 'greeting':")
replace('tools/c_guest/node.py', "'invalid-wire': (2, 4)}[category]", "'invalid-wire': (2, 4), 'platform-failure': (4,)}[category]")
replace('tools/c_guest/node.py', "    else:\n        require(value['category'] in ('local-error', 'platform-failure'), 'C-malformed-call-category')", '''    elif category == 'platform-failure':
        require(value['category'] == 'platform-failure', 'C-containment-failure-category')
    else:
        require(value['category'] in ('local-error', 'platform-failure'), 'C-malformed-call-category')''')
replace('tools/c_guest/node.py', "    cases = read_json(SDK / 'projects/cases.json')", '''    cases = read_json(SDK / 'projects/cases.json')
    cases['containment'] = {'function': 'run', 'success': [[0]], 'declaredError': [],
                            'invalidWire': [[]], 'failures': [[1], [2], [3]]}''')
replace('tools/c_guest/node.py', "for name in ('greeting', 'word-count', 'shipping'):",
        "for name in ('greeting', 'word-count', 'shipping', 'containment'):")
replace('tools/c_guest/node.py', '            for category, values in groups:', '''            for fault in case.get('failures', []):
                groups.extend([('platform-failure', [fault]), ('success', [[0]])])
            for category, values in groups:''')

# Preserve the complete existing contracts gate, sharing already built tools.
replace('tools/validate_contracts.sh', 'cargo build -p latent -p latentd --locked\n', '''cargo build -p latent -p latentd --locked
# Maintained C authoring: actual sources, locked generated ABI, native sanitizer
# ownership checks and authenticated separate CLI/node execution and cleanup.
(
  C_AUTHORING_ROOT="$(mktemp -d "${TARGET_ROOT}/c-authoring.XXXXXX")"
  trap 'rm -rf -- "${C_AUTHORING_ROOT}"' EXIT
  python3 -m tools.c_guest.qualify --output "${C_AUTHORING_ROOT}/projects"
  LSF_C_AUTHORING_BUILD_ROOT="${C_AUTHORING_ROOT}/projects" \\
  LSF_C_AUTHORING_FIXTURE_ROOT="${C_AUTHORING_ROOT}/fixture" \\
    timeout 180 cargo test -p latent-wasmtime --test c_guest_authoring --locked -- \\
      export_c_authoring_fixture --exact --ignored --nocapture --test-threads=1
  timeout 240 python3 -m tools.c_guest.node \\
    --cli "${TARGET_ROOT}/debug/latent" --node "${TARGET_ROOT}/debug/latentd" \\
    --fixture "${C_AUTHORING_ROOT}/fixture" --output "${C_AUTHORING_ROOT}/node"
  mkdir -p "${OUTPUT}/c-authoring"
  cp "${C_AUTHORING_ROOT}/projects/qualification.json" "${OUTPUT}/c-authoring/qualification.json"
  cp "${C_AUTHORING_ROOT}/node/receipt.json" "${OUTPUT}/c-authoring/node-receipt.json"
)
''')

path = ROOT / 'tools/ci/suites.json'
suites = json.loads(path.read_text())
assert 'c-guest-authoring' not in suites['selections']
assert not any(item.get('target') == 'c_guest_authoring' for item in suites['suites'])
reference = next(item for item in suites['suites'] if item.get('package') == 'latent-wasmtime' and item.get('target') == 'guest_sdk')
new = copy.deepcopy(reference)
new.update(id='latent-wasmtime.test.c-guest-authoring', target='c_guest_authoring',
    sources=['crates/latent-wasmtime/tests/c_guest_authoring.rs'], minimumCases=1,
    expectedCases=['export_c_authoring_fixture'], ignoredLeaves=['export_c_authoring_fixture'],
    expectedIgnored=['export_c_authoring_fixture'], timeoutSeconds=180,
    ownerSelections=['c-guest-authoring'], resourceClass='host-bounded',
    prerequisites=['fresh C authoring project builds', 'pinned C toolchain', 'public ephemeral signing fixture'],
    profiles=['full-change', 'full-manual', 'full-periodic'])
suites['suites'].append(new)
suites['suites'].sort(key=lambda item: item['id'])
suites['selections']['c-guest-authoring'] = [{
    'suite': new['id'], 'runner': 'validate_contracts', 'names': ['export_c_authoring_fixture'],
    'ignored': True, 'exact': True, 'filter': 'export_c_authoring_fixture'}]
path.write_text(json.dumps(suites, indent=2, sort_keys=True) + '\n')

(ROOT / 'sdk/c-guest/README.md').write_text('''# C capsule guest SDK

Author real C implementations of WIT contracts, compile a pinned Wasm component,
and use the normal signed-package admission and deployment pipeline. This SDK
runs **inside** a capsule; the external C control/client SDK is under `sdk/c`.

Start with the [C authoring guide](../../docs/component-development/c-capsule-authoring.md)
and [ownership contract](../../docs/component-development/c-ownership.md).
From the repository root with the exact toolchain pins installed:

```sh
python3 tools/c_guest_authoring.py new target/my-greeting --template greeting
python3 tools/c_guest_authoring.py bindings --project target/my-greeting --output target/my-greeting-bindings --update
python3 tools/c_guest_authoring.py build --project target/my-greeting --output target/my-greeting-build
```

The guide continues through package inspection, independently approved publisher
and builder evidence, real-node publication, deployment, invocation and cleanup.
Set the project's explicit `sourceRepository` before publishing your own source.
Build output and a local observation are not execution authorization.

`projects/` contains greeting, word-count and shipping source templates. The
public headers in `include/lsf/` provide bounded allocation scopes, explicit
result cleanup, secret zeroization, unique resource owners and retained async
frames. Generate the application's `probe.h`; never copy a handwritten ABI.
`wit/world.wit` describes the current reference capability surface, while
application worlds import only their actual required interfaces.

`examples/` and `blob.c` implement all nine shared Rust/C capability profiles:
HTTP, streaming, blobs, secrets, events, random, metrics, caller and callee.
`bindings.lock.json`, `capabilities.lock.json` and each project's binding lock
check actual generated output identities. Normal builds do not update them.

`tests/ownership.c` runs against generated headers under AddressSanitizer and
UndefinedBehaviorSanitizer. `tests/containment` is a separately signed fault
capsule for real-node trap, memory exhaustion, deadline and fresh-state checks;
it is deliberately not a user project template. Native tests are distinct from
the real signed capability and authenticated separate-process node tests.

The required Repository contracts gate executes all of these paths and retains
C qualification and node measurements under `target/contracts/c-authoring`.
No C helper introduces a service-owned thread, process, socket, execution pool,
provider, persistent guest heap or grant constructor. Profiles and observed
limitations are recorded in the [developer journal](../../docs/development/c-capsule-authoring-journal.md).
''')
replace('docs/component-development/guest-sdk.md', '''The maintained guest SDK is [Rust `latent-guest`](../../sdk/rust-guest/README.md).
A [C fixture](../../sdk/c-guest/README.md) checks generated canonical ABI ownership.''', '''The maintained guest SDKs include [Rust `latent-guest`](../../sdk/rust-guest/README.md)
and the [C guest SDK](../../sdk/c-guest/README.md). The
[C authoring guide](c-capsule-authoring.md) starts from a new source project;
[C ownership](c-ownership.md) covers generated values, resources and async frames.''')
replace('docs/component-development/guest-sdk.md', '`wit-bindgen` 0.60.0', '`wit-bindgen` 0.62.0')
replace('docs/component-development/guest-sdk.md', 'callee. It also compiles the C blob fixture.',
        'callee. It compiles all nine C peers against the same WIT and executes both\nlanguages against the same signed admission and runtime assertions.')
replace('docs/component-development/guest-sdk.md', '''The examples map imports to the same generated Rust
types and C builds against the generated headers.''', '''The examples map imports to the same generated Rust
types and C builds against the generated headers. C additionally checks the
reference SDK, every capability profile and each authoring project's generated
header/source/component-type identities; namespace aliases are derived only from
actual generated declarations.''')
replace('docs/component-development/guest-sdk.md', '''generator, compiles all examples and runs the signed guest suite.''', '''generator, compiles all examples and runs the signed guest suite. It also runs
native C ownership sanitizers and fresh C projects through actual authenticated
CLI/node publication, invocation, fault recovery and deployment cleanup, retaining
scoped measurements under `target/contracts/c-authoring`.''')

# Remove temporary authoring transports before evaluating required workflow
# identities. This does not change the baseline required CI command topology.
for name in ('c-guest-authoring-bootstrap.yml', 'c-guest-authoring-projects.yml'):
    (ROOT / '.github/workflows' / name).unlink()
Path(__file__).unlink()
from tools import ci_coverage
path = ROOT / 'tools/ci/commands.json'
commands = json.loads(path.read_text())
actual = ci_coverage.commands(ROOT)
assert actual == commands['after'], 'required CI topology unexpectedly changed'
commands['workflowIdentities'] = ci_coverage.workflow_identities(ROOT)
commands['delegatedOwners'] = ci_coverage.delegated_owners(ROOT, actual)
commands['pythonTestModules'] = sorted(path.relative_to(ROOT).as_posix() for path in (ROOT / 'tools/tests').glob('test_*.py'))
commands['pythonCases'] = ci_coverage.python_cases(ROOT)
path.write_text(json.dumps(commands, indent=2, sort_keys=True) + '\n')
ci_coverage.validate()
print('Applied reviewed C gate ownership, source guides and real-node fault cases')
