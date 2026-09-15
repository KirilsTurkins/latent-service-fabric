# Angular in generic execution cells

The installed `angular-ssr-component-v1` profile implements the public async
`latent:web/application@0.1.0.handle` contract using the ordinary Wasmtime
backend. [ADR-0040](../../adr/0040-run-the-closed-angular-adapter-in-fresh-generic-stores.md)
defines its integration and compatibility boundary. The fixed
[adapter](../../tools/angular-renderer-adapter/README.md) is composed with the
closed JavaScript engine before publication. The private synchronous engine
interface is not a node import or an SDK API.

## Configuration and identity

Add `rendererProfile: "angular-ssr-component-v1"` to an explicitly controlled
`local-experimental-v1` node. Reserve the workload's source, memory and CPU
through the normal settings; for the maintained fixture these include a
32 MiB `limits.maximumComponentBytes`, 2 MiB `limits.maximumPayloadBytes`,
256 MiB cell memory and 2,000,000,000 `execution.maximumCpuFuel`. The opt-in
does not increase those budgets. Node allocator/optimization must remain
`on-demand`/`speed`. It selects a 2 MiB Wasm stack, 4 MiB async stack and the
bounded composition shape for the shared engine.

A callable capsule declares `compatibility.renderer` with `profile` and
`profileDigest`, obtained from `RendererRequirement::angular()` or
`renderer_profile_digest(AngularSsrComponentV1)`. Do not hardcode a digest:
it binds the fixed adapter sources and ABI, and changes when those inputs do.
The capsule world remains tenant-owned and exports the shared public web
interface. Require single-threaded stateless execution, disable snapshots and
fusion, and declare at most 256 MiB aggregate linear memory, 2 billion fuel and
5,000 ms wall time. Deployment/caller budgets may be lower.

The runtime rejects an absent or different installed profile and validates
the actual composed surface before compiling or loading native code. Exact
component/package metadata, native engine/target/CPU settings, security profile
and host ABI remain separate preparation inputs. Cached code never carries a
publication's authority: the ordinary catalog lifecycle and guarded activation
start remain required.

## Request ownership and limits

Each invocation receives a new Store, JavaScript heap, module globals, Angular
injector, transfer state and callback queues. The adapter gets identity,
lineage, trace and deadline from sealed host context. Cookies are opaque request
data. The fixture validates hydration data and a module counter across users
and after failures. No application-owned instance, event loop or timer remains
when the Store is destroyed.

Two component memories share one aggregate memory charge. The adapter limits
private JSON input/result frames to 256 KiB/1 MiB and HTML to 128 KiB. The
shared public HTTP codec and delivery owner retain their own finite buffers.
Timers allow 256 cumulative zero-delay callbacks; explicit microtasks allow
4,096. Positive timers, intervals and mutation of the timer hooks fail. Native
Promise chains additionally consume fuel/memory and observe cancellation.
Fuel or deadlines may reject work below a byte ceiling.

Preparation uses the existing finite shared job/waiter/cache limits. The HTTP
listener preserves the original selected publication and request budget.
Disconnect transfers ownership to the normal cleanup supervisor until the
actual guest and delivery owners retire; revocation rejects before a fresh
Store starts. Store memory accounting does not represent total process RSS.

## Validation and remaining integration

After installing the pinned npm dependencies without lifecycle scripts, build
the maintained qualification bundle with `npm run build` in
`examples/renderer-profile`. Then run `python3 tools/build_angular_renderer.py`
from the repository root. It composes the public fixture under
`examples/renderer-profile/dist/runtime/application.wasm`.

The CI gate uses `tools/run_angular_renderer_tests.py` with the workspace test
manifest and that exact component. It executes real generic-backend and HTTP
node regressions, including failures, concurrent progress, disconnect and
revocation. Missing fixtures fail the gate. No binary or bulk report is checked
in. The original [qualification evidence](../testing/angular-renderer-qualification.md)
remains historical; #239 measures integrated release-build performance.

The observed application builder is #234, componentless web deployment
management is #226, and browser delivery defenses are #235. The current runtime
explicitly refuses Angular under `external-capsule-v1`: T1 requires those
actual package/build/authority paths and their conformance evidence. It cannot
be enabled by relabeling Angular output as a Rust or C build. This profile
does not provide an ambient Node process or arbitrary Node package support.
