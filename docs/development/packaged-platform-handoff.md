# Packaged Windows and Linux platform handoff

All five required platform entries passed the final packaged schedule in
[run 36187710975](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36187710975).
This handoff supplies completed platform evidence for #560/#561/#563/#564/#565/#566.
The editor-fix candidates, clean-machine newcomer walkthrough and final combined
review remain with #568/#569; this record does not close epic #559.

Application packages were independently approved at
`0cb5cf08f1d7eb53650c116c93dcdd4c4a4d6bc3`. Their developer-tool build was
[36164649914](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36164649914)
and the disposable-test runtime build was
[36164724959](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36164724959).
The final conductor was `f710f8abf78f94ce79af4f44586585467dc3dafa`, merged in #597.
The [compact observation](packaged-platform-handoff-observation.json) retains raw
receipt digests, approved policy digests, actual outcomes, component/tool identities
and cleanup. It keeps installed-artifact and source-built evidence separate.

## Actual packaged entries

| Entry | Actual environment and outcome |
| --- | --- |
| Windows/WSL2 | Windows x86-64 `10.0.26100`; WSL 2.7.14; Ubuntu 24.04.5 with kernel `6.18.33.2-microsoft-standard-WSL2`; all six languages |
| Native Windows | Same Windows host, after its owned WSL distro was purged; the exact exported components executed without Linux or a VM |
| Direct Linux | Fresh Ubuntu 24.04.5 OS container with kernel `6.17.0-1022-azure`; no application source checkout or runtime compiler; unprivileged node account |
| Explicit SSH | Same Linux OS environment, a separately selected account, pinned host identity and private credentials; no ambient SSH authority |
| Devcontainer | Generated opt-in terminal client on the hosted Linux Docker engine, Dev Container CLI 0.89.0, a separate explicitly selected SSH peer and unprivileged node |

The [Windows artifact](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36187710975/artifacts/10888256580)
contains the complete node/native and separate recovery observations. The
[Linux artifact](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36187710975/artifacts/10889790596)
contains direct/SSH and generated-devcontainer observations. The prior complete
[expanded run](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36184150835)
also passed all entries. No skipped job is used as platform evidence.

The Windows runner image contains development tools, but the application frontend
received a restricted environment with only System32 on PATH. Python ran the
separate conductor. The application did not use an LSF checkout or build LSF.
On Linux, the conductor recorded absent host compilers and disconnected networking;
selected authenticated guest compilers were installed explicitly for application
builds. Clean application execution does not mean the hosted runner image contains
no unrelated software.

## Acceptance mapping

| Requirement | Evidence |
| --- | --- |
| Offline authenticated bootstrap | Frontend/helper/runtime/compiler inventories verified against the independently approved exact source; actual wrong-target, changed-archive and wrong-publisher rejections preceded usable cache creation |
| Real lifecycle | Authenticated readiness, status/logs, typed invocation, ordinary stop, retained restart and exact-owner purge on Windows/WSL, direct Linux and SSH |
| Six maintained recipes | Rust, C, TypeScript, Go, Java and C# created and built outside checkout; success/declared-error cases passed on the node and native Windows host; Go/Java/C# also passed applicable runtime-capability denial and recovery |
| Byte-preserving source transfer | Spaces/non-ASCII author paths, all 37 CRLF lines and matching source digest; installed rejection of traversal, ABI mismatch, unknown descriptor fields, Unicode aliases and hard links; Unix symlinks also rejected |
| Workspace protection | Distinct WSL Linux users, private `0600` credentials, both directions of cross-home denial, excluded source `.env`, and another workspace remaining callable through stop/purge; direct/SSH and devcontainer isolation passed |
| Watch ordering and retention | A remained pinned in flight while B served new calls; one Invoke and one Cancel; slow compiler child reaped, only latest value 501 deployed, at most four retained attempts |
| Failure and authority | Compiler error and malformed replacement retained the working revision; revoked restore left controller and server deployments unchanged; focused test failure stayed visible without rollback |
| Exact response recovery | Lost successful publication, deployment and Invoke responses reconciled their original identities; new mutations blocked; no accepted effect replayed |
| Actual WSL interruption | Only the recorded owned distro was terminated and resumed; new guest identity confirmed old-process reaping, reported unclean shutdown and retained the deployment |
| Expired/unknown receipts | Separate real Windows schedule let a terminal receipt expire naturally, retained original UNKNOWN intent and protected a concurrent actor's generation; private intents remained intact after owned shutdown |
| Minimum test-host failures | Cold/warm fresh state, declared error, trap, fuel, memory, deadline, running-node cancellation and post-failure success executed on actual nodes; native supported subsets and reviewed differences remained explicit |

The owned WSL interruption is the actual platform-lifecycle alternative allowed
by #569. The physical Windows host was not suspended. No global WSL shutdown,
default-distro change, synthetic pressure data or public management endpoint was
used. Node readiness reports identify `local-experimental-v1`; signed application
fixtures and the provider-free trusted-local watch fixture are separately recorded.
These observations do not certify the external-capsule profile or a production
Windows node.

The native host's running-node cancellation requirement was rejected before any
native process started. Its separately selected cancellation-before-start case
passed. See [native Windows qualification](native-windows-qualification.md) for
the full support boundary and deterministic comparison records.

## Source campaigns and focused regressions

The same `0cb5cf08` developer build passed eleven actual source-built campaigns:
clock, failure, HTTP, immutable blob, scoped secret, metrics, local caller/callee,
events, watch, cross-account isolation and operation recovery. Their exact receipt
digests and cleanup dispositions are retained in the compact observation. These
exercise the production node/provider paths and explicit test seams; they are
not relabeled authenticated installation runs. The event peer implements a bounded
authenticated NATS protocol fixture and is not a live-broker qualification.

The existing controller inventories retain the smaller failure-boundary regressions:
interrupted extraction/resume, changed completed caches, unsafe partial trees,
private ACLs/Unix owners, competing controllers, missing readiness, failed/overflowing
helper children, finite transport loss, source changes/deletions, stale builds,
untrusted recipes and idempotent owned cleanup. #597 passed all 19 final checks
with nine conditional skips. Registered unit fixtures are not used in place of
the actual WSL/direct/SSH/devcontainer observations above.

Earlier failed attempts remain linked from
[packaged qualification](packaged-developer-qualification.md). The editor test
subsequently found buffered diagnostics and produced #599; its replacement
candidate identity and newcomer review remain separate final work. Mac, Lima and
ARM64 are excluded from the accepted scope, not untested support claims.
