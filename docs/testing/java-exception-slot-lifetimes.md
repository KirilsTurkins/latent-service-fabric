# Java activation exception-buffer lifetimes

## Failure and scope

PR #2156's stack-first layout protects static data from a downward native-stack
overrun, but it does not make the original programme fit the unchanged stack.
In Java authoring run `44540762777`, job `135618505095`, compiler preparation
passed, signed fiber mode 0 returned 42 and retired its owners, and mode 1 failed
with `GuestTrap: memory-out-of-bounds`. Its later modes and stages did not run.

The retained artifact `14539762517` has SHA-256
`39446eefffadfe3be659d374da9235ec09b8eabb91a95bbaabef7a8ff5f5c9a2`.
Its main core contains many distinct exception-handler buffer allocations in
large generated methods. A separate unsigned mock-host diagnostic, with only a
stack-pointer export added to that core, stopped during worker startup with a
stack pointer of -240. That observation is not signed-node or host-ledger
qualification. It identifies native-stack exhaustion, not a need to accept
malformed bridge results or increase the guest's resource allowance.

## Storage repair

`tools/java_guest/exception_slots.py` validates the generated C before either
activation link route preprocesses and seals it. It recognizes the structured
whole-line `TEAVM_TRY`, `TEAVM_CATCH` and `TEAVM_END_TRY` regions in each generated
native function. When there are more regions than simultaneously nested levels,
it allocates one automatic `TeaVM_LongjmpDesc` per lexical nesting level and
reuses that object for later disjoint regions in the same native invocation.

The original TeaVM 0.15.0 `exceptions.h` must have SHA-256
`024e4fafa0a2cd330911b5d84d1b929f928a88d74730cc265d08cbbb940eb368`.
The repair appends an activation-only parameterized form of its exact TRY macro,
removing only that macro's per-region local declaration. The original header,
setjmp calls, catch/restore/rethrow macros, callbacks, spills, control transfers
and continuations remain unchanged. Every region still executes its own setjmp.

A descriptor is linked only during its active native handler. The original
restore unlinks it before a later disjoint region can reuse it. Nested handlers
have separate variables, and recursion creates a fresh set in every native
invocation. The objects are not an array, static storage, heap allocations or
cross-invocation state. No handler is removed or merged.

The adapter rejects an unexpected header, malformed region nesting, conflicting
macro definitions, reserved identifiers, line-spliced class source, unsupported
preprocessor control, symlinks, source drift and existing source-bound violations.
It validates every selected input before writing, records before/after hashes,
and enters the existing generated-source inventory before preprocessing. Both
the ordinary guarded link and Date-owned link consume the resulting sealed
bytes. The helper is included in the source-bound build recipe, so it cannot
reuse the old prepared-input identity.

This does not change FULL/O2 optimization, the 65,536-byte stack, 67,108,864-byte
maximum memory, compiler pins, ordinary non-activation compilation, guest source,
strict wire decoding, signed expected results, grants or host resource ceilings.

## Evidence and limits

The selected compiler-free regression pass contains 81 tests, including all 56
Java qualification tests. Real subprocess execution was blocked in that pass.
The new controls cover sequential versus nested storage, separate functions,
comments/literals, malformed input, exact header identity, all-input validation
before mutation, recipe identity and both guarded link routes. The link-route
controls mock the compiler; they are not compiler execution evidence.

Applying the adapter to three retained generated-C trees from the same artifact
validated 163 regions into 39 slots, 142 into 36, and 3 into 1. Those are other
qualification programmes, not the failed fibers' omitted generated-C tree.
This checks acceptance of real emitted syntax, not execution of those products.

The native witness below passed with Clang 17 and GCC 14 at `-O2`, before and
after adaptation. It exercises normal exit, caught exceptions, nested handlers,
default rethrow, throwing from a catch, explicit restoration before a goto, and
recursive invocations. A negative control that aliases a nested descriptor to
its active outer descriptor fails its lifetime assertion. A separate generated
160-region stress witness executed every exceptional region in both variants.
GCC's native stack-usage report decreased from 33,344 bytes to 272; native Clang
already reused storage and reported 248 in both variants. These are native-host
measurements, not measurements of the pinned Wasm compiler or the signed guest.

Fresh pinned-compiler preparation, all twelve original signed calls, subsequent
Java stages and current-head CI remain required. No successful signed repair is
claimed by these local controls. The separately stopped scheduled compiler-model
qualification and development merge hold are not lifted.

## Reproduce the native lifetime witness

From the repository root, with Python, Clang or GCC, and a native C standard
library available:

```sh
out="$(mktemp -d)"
export out
python3 - <<'PY'
import os
from pathlib import Path
import shutil
from tools.java_guest.exception_slots import stage
source = Path('tools/tests/fixtures/java-exception-slots')
for kind in ('baseline', 'shared'):
    target = Path(os.environ['out']) / kind
    target.mkdir()
    for path in source.iterdir():
        if path.suffix in ('.c', '.h'):
            shutil.copyfile(path, target / path.name)
    if kind == 'shared':
        print(stage(target))
PY
for kind in baseline shared; do
  reuse=0
  if [ "$kind" = shared ]; then reuse=1; fi
  cc -std=c11 -O2 -Wall -Wextra -Werror \
    -DLSF_JAVA_ACTIVATION_PROFILE=1 -DLSF_EXPECT_REUSE="$reuse" \
    -I "$out/$kind" "$out/$kind/probe.c" -o "$out/$kind/probe" || exit 1
  timeout 10s "$out/$kind/probe" || exit 1
done
```

These fixture headers model only the descriptor and shadow-stack fields used by
the original exception macros. They are not replacements for the SDK runtime.

## Independent Rust cleanup-observation failure

CI run `44540763151`, Rust test job `135621047429`, failed in
`connect_policy_revocation_before_registration_refuses_handoff` when the final
pool snapshot raced a cleanup worker holding the capacity mutex. The failing
error was `ResourceExhausted: capability-busy`, after the socket EOF observation.

The test now yields within a two-second deadline only for that exact busy
snapshot error. The first readable snapshot must still have zero connections;
an unsettled nonzero snapshot, another error or a persistent busy state fails.
The assertion remains before fixture cleanup and does not relax policy refusal,
physical socket closure or native-settlement requirements. Its real Rust test
execution remains a CI responsibility; no local Rust execution is claimed.
