# C guest SDK

For an application tutorial, use [Creating a compiler profile](../../docs/component-development/creating-a-capsule.md)
and select your language. The language profile below describes compiler and
custom packaging details.

Start with [C compiler profile](../../docs/component-development/c-authoring.md).
It creates an independent project and walks through WIT, compilation, packaging,
signing, enforced admission, publication, deployment, invocation and cleanup.
This guest SDK is separate from the external C control-plane client in `../c`.

The explicit [transactional aggregate template](../../docs/component-development/transactional-authoring.md)
uses `lsf/state.h` and `lsf/intents.h` with generated state 0.2 owners and the
canonical shared transaction type. Callback frames retain borrowed inputs and
leases until physical retirement, returned buffers have explicit deep close,
and pages retain their original view. The host owns commitment. The separately
admitted Phase 4 profile and signed Linux-node matrix are tracked by #389.

The maintained toolchain is Zig 0.16.0 (`zig cc`, default C11, `wasm32-wasi`, `-O2`),
wit-bindgen 0.62.0 and wasm-tools 1.254.0. Generated bindings preserve WIT
identity, async imports, `uint64_t`, UTF-8 strings, records, lists, options,
results and owned/borrowed resources. They are generated from the selected WIT,
not a handwritten second ABI. The contract derivation tool explicitly rejects
unsupported public shapes; see the [guest reference](../../docs/component-development/guest-sdk.md).

An explicit [C23 resource selection](../../docs/component-development/c-compiled-resources.md)
enables ordinary `#embed` over captured immutable data and projects declared
dependency resources into the shared package index. It installs no runtime
filesystem or writable scratch. The retained
[source-bound C23 signed receipt](../../docs/testing/evidence/c23-resources-passed-2026-10-19.json)
records the earlier resource campaign; the C11 and facility receipts retain
their own scope. Ordinary closed `fopen`/`tmpfile` behavior is documented in
[packaged resources](../../docs/component-development/packaged-resources.md).

The base reactor has a 64 KiB stack, a finite memory maximum and no thread runtime.
Zig's bundled libc supplies allocation. Component construction rejects ambient
WASI imports: filesystem, sockets, environment and clocks are not automatically
available. Applications do not create provider clients, grants or credentials.
The ordinary host deployment policy remains the only source of authority.

The separate [C runtime context](../../docs/development/c-runtime-context.md)
and [authenticated thread preparation](../../docs/development/c-thread-preparation.md)
paths target a finite cooperative context-144 profile. They require matching
compiler/core, component graph and explicit host selection; the base recipe does
not enable them. Their source/component evidence does not qualify arbitrary
pthread/C11 libraries, standard networking or safe CPU-loop preemption.
Ordinary libc clock, entropy and stdio ports have their own
[standard-facility contract](../../docs/component-development/c-standard-facilities.md)
and current capability grants.

## Owners and asynchronous calls

Development's [libfetch profile](../../docs/component-development/c-authoring.md#ordinary-libfetch-http-profile)
provides separately authorized GET/HEAD and bounded resume-offset handling; the
typed host provider owns transport/TLS. The cooperative runtime also preserves
pthread/C11 once initialization across an owned wait, using the original context
as the initializer and waking contenders only after publication. See
[C runtime context](../../docs/development/c-runtime-context.md) for source and
the separate signed contention owner. Neither path supplies general POSIX or
unqualified native thread support.

`include/lsf/ownership.h` defines an explicit bounded scope (32 entries plus a
caller-selected byte limit). Allocation, adoption, detach and release have
separate ownership meanings. Close runs remaining cleanup in reverse order;
detach transfers ownership without claiming a host-budget refund. A generated
export's post-return owner frees transferred strings. Borrowed literals must
never be freed or returned as owned strings.

`async.h` retains task input and result frames across pending canonical calls,
distinguishes cancellation with and without returned data, and retires subtasks
before clearing context. C provides no borrow checker: copying an owner or
freeing input before a subtask retires is an application bug. Do not keep frames
in globals across invocations. The activation teardown also reclaims memory
when a trap prevents guest cleanup; it does not undo external effects.

`http.h` closes nested response allocations; `streaming.h` and `blob.h` track
affine chunks, request uploads, response bodies and primitive handles.
`secrets.h` zeroizes its owned bytes before freeing them. `service.h` preserves
child result classifications. Events, randomness and metrics use the generated
typed imports directly. Every capability has an executable source under
`examples/` (blob ownership is in `blob.c`). No wrapper retries or grants access.

## Selected literal IPv4 streams

A cooperative project may select the bounded stream source profile:

```sh
python3 tools/c_capsule.py new ./my-capsule \
  --threading-profile c-context144-sync-cooperative-v1 \
  --runtime-profile c-stream-clock-entropy-v1
```

This creator currently uses the greeting template and emits its public `greet`
as an async WIT export, as required by the cooperative context. Its ordinary C
implementation remains synchronous. Other templates need a compatible public
export before they can use this profile.

The profile maps selected-source socket calls onto the existing
`latent:network/streams@0.1.0` provider. It accepts up to eight invocation-local
blocking IPv4 stream descriptors, and `connect` uses the actual numeric address
and port from `sockaddr_in`. The operator must separately grant that exact TCP
endpoint, the stream provider, clocks, entropy and the cooperative runtime.
No hostname grant is converted to an address grant, and this profile does not
resolve hostnames.

Selected C source can use `getaddrinfo` and `freeaddrinfo` for strictly dotted
decimal IPv4 addresses and a decimal port from 0 through 65535. A missing
service selects port 0; a missing node or nonnumeric hostname returns
`EAI_NONAME` without contacting a resolver. Named services return `EAI_SERVICE`
(or `EAI_NONAME` with `AI_NUMERICSERV`), and ports beyond the five-digit,
65535 bound return `EAI_SERVICE`. The supported flags are `AI_NUMERICHOST`,
`AI_NUMERICSERV` and `AI_CANONNAME`. The last returns an owned canonical
numeric literal derived from the parsed address, not a hostname or a grant.
Flags such as `AI_ADDRCONFIG` and `AI_PASSIVE` return `EAI_BADFLAGS`. IPv6 returns
`EAI_FAMILY`, and datagram or non-TCP requests return `EAI_SOCKTYPE`. Each
successful call owns a separate result in the original bounded guest memory;
`freeaddrinfo` releases it. The result is not an endpoint grant, and legacy
hostname lookup functions remain unavailable. `gai_strerror` provides static
C-locale messages for resolver error codes without consulting a host resolver.
`getnameinfo` renders a supplied IPv4 address or port only when the requested
output has `NI_NUMERICHOST` or `NI_NUMERICSERV`, respectively; it performs no
reverse lookup or service-name lookup and creates no endpoint grant. A requested
non-numeric result returns `EAI_NONAME`, and a short output returns
`EAI_OVERFLOW`. Other flags return `EAI_BADFLAGS`; for example, unlike native
implementations, `NI_NUMERICHOST | NI_NAMEREQD` is rejected as unsupported.

The captured component build selects this implementation when it is present
in the project's verified SDK snapshot. Previously captured projects without
the source retain their original behavior: a call to this API fails to link.
To use the new source, create a project with the current tool bundle and migrate
the application source, WIT and dependency declarations through normal review;
editing a project's vendored SDK invalidates its lock. The SDK can prepare a
verified [CMake feature-probe kit](../../docs/component-development/c-dependencies.md#captured-cmake-feature-probes)
for a separate dependency configuration step. Detection exposes only this
numeric subset and does not qualify a client or its complete behavior.

One-descriptor `select`/`pselect` supports readable and writable interest with
a NULL timeout; the provider and activation deadlines still apply. Finite
descriptor wait timeouts, including zero-time polling, are refused because the
provider's timeout result does not distinguish observation expiry from expiry
of the original connection or activation. Concurrent use or close of a busy
descriptor is refused. Exceptional descriptor sets, descriptor `poll`, nonblocking mode,
socket option changes, local bind, IPv6 and unsupported message flags are refused;
`SO_TYPE` is observable, with output truncated to the supplied buffer length,
and TLS is not supplied by this profile.
`SO_RCVTIMEO` can be named by selected source, but `setsockopt` returns
`ENOTSUP` for it, including a zero value. Libraries that ignore this error do
not receive their requested socket deadline; use only their untimed mode with
this profile, subject to the original provider and activation deadlines.
Selected-source `send` accepts `MSG_NOSIGNAL` (using the pinned WASI preview2
value `0x4000`) with the same write and error behavior as flag zero. The adapter
does not raise `SIGPIPE`, with or without this flag. The flag does not enable
signals or other message flags. Other `send` flags and every nonzero `recv` flag
are refused.
`SOCK_CLOEXEC` at creation and `F_GETFD`/`F_SETFD` retain the descriptor's
`FD_CLOEXEC` flag. `F_SETFL` accepts only `0` or `O_RDWR`, which preserve the
already-blocking descriptor state; nonblocking and other status flags are
refused. This operation does not qualify a TLS client. Other descriptor flags
and duplication remain unsupported;
this profile does not provide process execution or descriptor inheritance.
`POLLPRI` for a live descriptor is never silently ignored. Descriptor-free
timer polls retain the existing timed runtime and accept at most 64 ignored
negative-descriptor entries. Calls inside prebuilt libc objects are not remapped.
Selected-source `read`, `write` and `close` route only to this socket table;
stdin, stdout and stderr are not socket descriptors and return `EBADF` through
those calls. This profile does not combine the separate standard-stdio logging
profile. Its socket table uses numbers 3 through 10: another independently
allocated descriptor matching an occupied slot would alias that socket on these
source-level calls. Do not combine it with another descriptor producer until
the profiles share a coordinated descriptor namespace.
After a successful send half-close, later sends return `EPIPE` without another
provider write, while reads remain available; repeated send half-close is local
and idempotent. `SHUT_RD` and `SHUT_RDWR` return `ENOTSUP` without changing
the descriptor: the v1 provider's `both` operation stops the transport and does
not preserve previously buffered input for a subsequent read.
An error after a possible write keeps the descriptor failed; the optional
`lsf_stream_last_error` reports its original error code, accepted prefix and
possible-effect bit while the descriptor remains open.

These are finite source-level capabilities. They do not establish signed node
execution, physical kernel retirement, general POSIX compatibility or libcurl
easy/multi support.

For applications that also use the bounded log-backed standard output, select
`c-stream-clock-entropy-stdio-v1` with the same cooperative threading profile.
This separate profile imports the existing log capability in addition to the
stream, clock and entropy capabilities; the operator must explicitly grant
each one and provide a nonzero `logBytes` budget. It does not grant authority.
Standard output and error use descriptors 1 and 2 and the existing bounded,
UTF-8 log implementation; socket descriptors remain 3 through 10. Selected-source
`write` routes those standard descriptors to that implementation and socket
descriptors to the stream provider; libc `close` uses the same bounded table.
Each stdio write submits at most 256 UTF-8 bytes in one log record. Longer
writes return the accepted prefix length at a character boundary, so callers
can continue with the remaining bytes; each accepted record uses its original
log budget. A rejected record reports no bytes written. An incomplete UTF-8
scalar at the end of the supplied input is not buffered across calls.
The four selected libc stdio calls are linked within the component core, with
no ambient WASI filesystem imports. Selected-source `read` of stdin returns
`EBADF`; an unchanged libc `fread(stdin, ...)` requires the unsupported preview1
`fd_read` and is refused during component construction. Closing stdout or stderr
returns `ENOTSUP`, and other file descriptors and mixed descriptor polling are
not supported. This combination has not been qualified through a signed node.

## Optional closed signal and jump declarations

A cooperative C project may explicitly select `c-closed-signal-jump-headers-v1`:

```sh
python3 tools/c_capsule.py new ./my-capsule \
  --threading-profile c-context144-sync-cooperative-v1 \
  --header-profile c-closed-signal-jump-headers-v1
```

The captured SDK and pinned Zig headers provide declarations for dependencies
that include `signal.h` or `setjmp.h` without using their operations. The compiler
places its separately compiled guard before application and captured dependency
objects; reachable SDK `signal`, `raise`, and nonlocal jump calls fail to link.
If an application supplies the guard's private refusal symbol, the signal call
traps. Static archives are unsupported for this selection. The normal profile
and its header errors remain unchanged.

This is a source-compilation boundary, not signal delivery or setjmp support.
Source that deliberately supplies its own macros or implementations is outside
that guarantee. The selected headers do not add sockets, descriptor readiness,
or a qualified libcurl library. The control uses a real captured compiler with
minimal binding and runtime stand-ins; it is not a signed component result.

## Verification

With the pinned tools installed, from the repository root:

```sh
python3 tools/qualify_c_capsules.py --output /tmp/my-fresh-c-qualification
```

The finite Linux gate creates five projects outside the runtime checkout,
compiles their actual editable C sources, checks generated SDK binding hashes,
and executes the printed beginner guide. It also builds the C and Rust
capability peers and runs the admitted Wasmtime tests for every capability.
The real-node gate checks denied authority, declared errors, deadline/cancel/
disconnect cleanup, trap/fuel/memory exhaustion, and fresh calls after failure.
It observes active owners and 5/9/17 dormant deployments with a two-entry shared
code cache; it does not claim production sizing or a full 100k-scale result.

Failed builds retain `BUILD-FAILED.json` and bounded compiler logs. Observations
bind captured inputs, actual tools and outputs; they are operator assertions,
not authenticated source or a complete transitive SBOM. Demo signing occurs
only after compilation in a separate process. The human newcomer review remains
the separate #345 gate.

Measured results and retained failed attempts are documented in the
[developer qualification report](../../docs/development/c-capsule-qualification.md).
