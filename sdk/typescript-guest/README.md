# TypeScript guest SDK

For an application tutorial, use [Creating a compiler profile](../../docs/component-development/creating-a-capsule.md)
and select your language. The language profile below describes compiler and
custom packaging details.

Use [TypeScript compiler profile](../../docs/component-development/typescript-authoring.md)
for an editable project, package/sign/admit/deploy/invoke/cleanup path.
This guest SDK is separate from the external Node client and closed Angular
renderer. It does not embed Node, a browser, or application-owned host threads.

The explicit source-owned async-import runtime can automatically install the
[buffered fetch candidate](../../docs/component-development/typescript-fetch-candidate.md)
under ordinary dependency global lookups when streaming HTTP is declared.
The [runtime capability matrix](../../docs/component-development/runtime-capabilities.md)
links the finite signed Fetch-client and runtime programmes. Each retains its
original source and provider identities; it does not qualify every dependency
or promote the synchronous profile below to an asynchronous runtime.

The explicit [transactional aggregate template](../../docs/component-development/transactional-authoring.md)
adds `state.Command`, `state.Query`, `state.Page` and the logical `intents.Intent`
builder. Versions remain `Uint8Array`, full-width sequences remain `bigint`,
and declared enum errors remain typed results. Shared owner cells retain the
original view during page calls and exclude close while calls/pages remain live.
The separately admitted Phase 4 profile and signed Linux-node execution matrix
are tracked by #389.

## Contract and compiler

`tools/typescript_capsule.py new` copies authoritative WIT and the immutable
reviewed SDK into an independent project. Edit `src/main.ts`, relative source
modules and `wit`; keep `vendor/lsf` unchanged. The build generates declarations,
typechecks the application, bundles captured modules, uses the locked maintained
ComponentizeJS compiler and packages the actual component. Tool, dependency and
source observations are retained.

The base profile's generator supplies a synchronous JavaScript ABI. The builder checks its
projected type graph and restores the original async WIT. Wasmtime suspends the
activation across host calls; no application process waits for a provider.
Return ordinary contract values, not promises. Each activation owns its guest
promise/microtask state and heap. The recovery test deliberately retains
unresolved promises until Store destruction, then requires fresh module state.

WIT `u64`/`s64` use `bigint`, UTF-8 strings preserve embedded NUL, byte lists
use `Uint8Array`, and records/results preserve generated types. The guarded
compiler adapter preserves signed i64 and unsigned i32 lowering bit patterns
at ComponentizeJS 0.22's internal embedding boundary. WIT types and canonical
lifting do not change. CI checks both signed extremes and unsigned maxima
through actual compiled components, including scalar returns and a declared
error raised across the generator's separate JavaScript realm. The exact
generated glue is retained with compiler diagnostics.

WIT future/stream/map/fixed-size-list values, named/free-standing imports and
colliding generated import filenames fail explicitly.
Public RPC parameters/results cannot contain owned or borrowed resource values,
including nested records/lists; authoritative contract derivation rejects them
before guest compilation. This does not narrow the declared blob/streaming
resource imports used by the capability wrappers. There is no ambient
clock, entropy, filesystem, network, timer, worker, process or DOM authority.
Ordinary `Math.random()` uses one fresh `u64-value` draw only when the exact
`latent:random/random@0.1.0` interface is declared and admitted. The high 53 bits
map to `[0, 1)`; this API is noncryptographic. Without that declaration it throws
a concrete unsupported error, with no deterministic or ambient fallback.
Application snapshot-time draws throw before a host call; engine bootstrap is
unchanged. See the [finite entropy contract](../../docs/component-development/typescript-standard-entropy.md).
The base profile rejects timers such as `setTimeout`; the explicit activation
runtime has separately bounded [timer and Promise semantics](../../docs/testing/typescript-runtime-semantics.md).
Effects require configured, declared LSF imports and host grants.

Ordinary npm dependencies use [capture and exact review](../../docs/component-development/typescript-dependencies.md).
Selected [Buffer modules](../../docs/component-development/typescript-buffer-profile.md),
[net.Socket](../../docs/component-development/typescript-node-net.md) and the
[published delay library](../../docs/component-development/typescript-published-delay.md)
have their own finite profiles and evidence. They do not install a Node process
or arbitrary Node built-ins. Dynamic loading and application compiler configuration
overrides remain outside the maintained build contract.
Relative JavaScript source modules require matching `.d.ts` declarations;
untyped imports fail the strict TypeScript check. TypeScript source modules
can be imported directly within the captured project.

## Typed capability wrappers

`capabilities/` imports exact generated interfaces, not a synthetic broker or
grant. `examples/` contains nine fixtures for all eight capabilities plus the
local-service callee.

| Module | Ownership |
| --- | --- |
| `http` | One buffered call and typed result; no retry. |
| `streaming` | Upload/body/chunk owners; finish/abort consumes; close invokes the generated destructor. |
| `blob` | Reader/writer handles close or seal explicitly; chunks materialize once and close explicitly. |
| `secrets` | Close zeroes owned bytes; application-created copies have their own lifetime. |
| `events` | Exact receipt/error/uncertainty; no hidden outbox or retry. |
| `service` | Returned, domain-error and platform-failure outcomes; host-controlled descendant budgets. |
| `random` | Host-authorized bounded bytes/full-width integers, never ambient entropy. |
| `metrics` | Exact instrument kind/attributes; no guest exporter or provider. |
| `state` (Phase 4) | Command/fresh-query owners, typed get/put/delete/scan, bounded pages and explicit close. |
| `intents` (Phase 4) | Logical intent builder stages through the canonical command owner; host-owned commitment. |

Owners reject use after close/consume and reentrant borrow. Aliases share live
state. Consuming calls invalidate before uncertain effects; destructors are
never retried. Use `try/finally` or a finite `Scope` closed in `finally`.
Scope teardown attempts every owner even after a destructor fails. GC
finalizers are not resource management.

Cancellation cannot prove an external effect did not occur. Charges remain
until the real owner is reclaimed. The host enforces permissions, input/output
bounds, deadlines, fuel, memory, pooling and containment after a guest trap.

The service SDK caller reserves a finite 240-second wall budget to cover cold
compilation of both embedded engines. Its callee and other examples retain
120 seconds. The host still gives the child only half of the parent's remaining
budget; the wrapper cannot extend that grant or retry a deadline failure.

## Qualification

After the guide's prerequisites, run from the checkout:

```sh
python3 tools/qualify_typescript_capsules.py \
  --tools "$LSF_TYPESCRIPT_TOOLS" \
  --output "$(mktemp -d)/typescript-authoring"
```

The gate builds five independent projects and nine SDK fixtures, exercises
production signature/admission and capability tests, and runs a real node
through valid/invalid tutorials, allowed/denied HTTP, cancellation, disconnect,
trap, memory/fuel exhaustion and fresh-state recovery. It measures dormant
populations, active owners, shared cache bounds and clean shutdown, and executes
the guide's six printed Bash steps.

Only `qualification.json` with `status: passed` is complete execution evidence.
`BUILD-COMPLETE.json` proves a build, not execution. Failed attempts keep their
own diagnostics. Synthetic value/broker models live only under `tests/model`;
they are neither exported by the SDK nor captured in application projects.
Their unit tests are supplementary, not provider or node qualification.
Newcomer review #345 and release publication
approval remain separate requirements.

Ordinary Date/performance compatibility uses the explicitly selected [standard clock boundary](../../docs/component-development/typescript-standard-clocks.md). Undeclared current-time reads fail concretely; deterministic Date arguments/parsing remain available. Its finite signed campaign is pending.
