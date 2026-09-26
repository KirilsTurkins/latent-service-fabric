# Bounded C delivery evidence

Scope: issue #261, native C source commit
`83ac3feb0e32dd847c2586b703dcfd23e02b015b`, reviewed/executed on 2026-09-19.
The worktree is `target/phase3-261`, branch `feat/261-bounded-c-client`.
It starts from origin/development and includes the authorized shared qualification
baseline `897c7d43` through merge `54ae1fff`. The C code commit itself touches only
`sdk/c/`; it changes neither public common models nor the shared SDK runner.

## Executed native checks

Execution used the independently owned Linux x86-64 container
`lsf-phase3-261-c-build`: CPU cap 2, memory cap 2 GiB, PID cap 256,
GCC `12.2.0-14+deb12u1`, glibc 2.36, Python 3.13.5. No host compiler installation
or parent `lsf-phase3-sdk-build` mutation was performed. The Docker outage's
interrupted work is not counted as either passing or failing; the complete
commands below were rerun after restarting only the existing C-owned container.

From this worktree:

```powershell
docker exec lsf-phase3-261-c-build python3 sdk/c/tools/validate.py --build-dir target/c-sdk
docker exec lsf-phase3-261-c-build python3 sdk/c/tools/validate.py --build-dir target/c-sdk-asan --sanitize
python sdk/c/tools/audit_dependencies.py --graph target/c-sdk/dependency-graph.cdx.json --report target/c-sdk/dependency-audit.json
git diff --check
```

Both complete native validation commands exited zero. Each ran three C tooling
unit tests, independent binding regeneration comparison, the unchanged C semantic
suite, 49 shared protobuf DTO round trips (retaining the existing semantic
assertions), the owner layout probe, private-file/parser tests and the native
HTTP/2 TCP-peer integration suite. This preserves the original 68 common semantic
cases; it does not mislabel local-only models or contradictory oneofs as valid
wire messages.

The final ordinary and sanitizer peer runs each reported:

```text
C owner layout: owner=1032 call=14960; fixed nghttp2 initialization allocations=232+152 bytes
C private configuration: bounded parsing, file permissions, symlink rejection and credential wiping passed
C allocation fault sweep: 38 injected failures across 160 positions
C HTTP/2/protobuf: eight RPCs, ownership, exact u64, audit absence/future, recovery, limits, deadlines, no retry, shutdown races passed
C controlled TCP peer: {"closed": 189, "connections": 189, "defaultCapabilityPages": 2, "requests": 235}
```

The peer is an independent TCP HTTP/2 implementation using official Python
protobuf bindings, not a C vtable fake or a purported real node. It asserts no
automatic resend after drop/refused-stream/GOAWAY and observes every accepted
connection physically closed. Counts can vary with intentional response/shutdown
scheduling; finite closure and exactly-once callbacks are the assertions.

Coverage includes all eight RPCs, all legacy RPCs/outcome/disposition conversions,
poisoned retained input buffers, copied callback results, exact zero/UINT64_MAX
numeric usage maps, absent/known/future audit metadata, original-ID recovery,
NotFound uncertainty, explicit manual replay/conflict, policy/capability page
differences, malformed/oversized/header-flood/contradictory replies, future enum
rejection with raw values, refused TCP, queue/retained/body/arena/aggregate bounds,
local and remote deadlines, late-callback admission, 24 stop/response orderings,
reentrant stop and inline allocation/invalid-request callback poll/destroy guards.
The 160 allocation positions cause **38 actual injected allocation failures**;
the remaining positions are not incorrectly reported as failures exercised.

The sanitizer build instruments both C SDK/nanopb and nghttp2 with ASan+UBSan.
Tests use `ASAN_OPTIONS=detect_leaks=1:halt_on_error=1` and
`UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1`. No sanitizer diagnostic was
emitted. This is a bounded native test run, not a load campaign, fuzzing proof,
thread-safety assertion, CI result or universal memory-safety guarantee.

The [dependency review](DEPENDENCIES.md) records source/tag/archive verification,
all 53 nghttp2 library source/header matches, bundled sfparse identity, current
public advisory decisions and the fresh nine-query OSV observation. The generated
CycloneDX graph and audit are under `target/c-sdk/`; they are generated evidence,
not ignored unknown dependencies or fabricated coverage guarantees.

## Actual separate-node qualification

Parent qualification on 2026-09-19 at integration source
`3584f589` ran this exact native participant through all 18 assertions against
a separately owned authenticated node and freshly signed maintained Rust
HTTP/blob/callee guests. Nine activation IDs were retained, six upstream
requests were authorized with zero unexpected requests, and all four held
upstream sockets physically closed. The runner independently verified terminal
status, the operation receipt and clean node/provider shutdown before reaping.
The raw receipt SHA-256 is
`6e04200fc97e6db34043070d1aae5d776ae8d8e7002d4ec2b1082a1b61e04867`;
the curated checkpoint is retained in shared qualification PR #366.

This replaces the prior unexecuted handoff status, not the controlled-peer
record. `tools/validate_sdks.sh` now requires ordinary and ASan/UBSan native
transport checks. The full six-language real-node CI matrix is still delivered
by PR #366; its exact-head gate and acceptance review remain prerequisites for
#261 closure. No installed-node, browser or whole-process isolation claim is
made by this local result.

### Executable and fixture contract

The compiled **native** participant is `target/c-sdk/provider-workflow`, invoked
as `provider-workflow --config /absolute/private/input.json`. Its non-sanitized
ELF SHA-256 for the recorded build is
`4c183d6a788b46decc1036ca6d9fd32ff7f7d2de68628c689c401d1310aef41b`.
`ldd` shows only libc and the ELF loader as dynamic dependencies. Binary identity
can depend on compiler/build paths; this is not a cross-host reproducibility claim.

The participant implements all 18 required checks from the
[shared contract](../../docs/testing/sdk-provider-workflow.md), including original
identities, all eight RPCs, absent policy acknowledgements (`auditAttempt:null`),
four distinct 3000/500 ms held-call cases, started/physically-closed markers and
retained terminal status. Its failure output uses only fixed stage/reason tokens
and bounded category/gRPC numbers. The smaller `provider-client` example invokes
authorized HTTP/blob guests but deliberately does not claim the 18-check result.

The parent owns integration into the shared validation runner. The measured
real-node pass above is not an installed-node qualification or CI result.
The clean-checkout commands are in the
[C README](README.md#clean-checkout-authorized-httpblob-example). A successful
shared runner receipt is attached in PR #366 rather than inferred from Rust/Node
results or the controlled peer.

Parent integration entry point: `python3 sdk/c/tools/validate.py --build-dir PATH`,
plus `--sanitize` with a separate build directory. The shared real-node runner
takes `--language c -- /absolute/provider-workflow`. No shared runner, other SDK,
security inventory, Docker volume or parent container was edited in this work.
