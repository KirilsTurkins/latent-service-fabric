# Angular renderer execution profile

[ADR-0037](../../adr/0037-qualify-a-closed-angular-component-renderer-profile.md)
selects `angular-ssr-component-v1` for Phase 3's first renderer adapter.
The [executable fixture](../../examples/renderer-profile/README.md) qualifies
real Angular SSR and hydration. The [installed generic-cell adapter](angular-renderer-runtime.md)
implements #233; the observed Angular build adapter remains #234. Exact package admission
and catalog lifecycle are implemented by the separate
[web release admission profile](../reference/web-release-admission.md) (#225).
That profile rejects this private proof ABI. The composed production adapter
exports the exact public async interface and has an explicit `rendererProfile`
node selector, separate from security policy. T1 remains gated pending the
observed Angular recipe and web deployment authority; arbitrary Angular/Node
compatibility is not implied.

## Qualified inputs and identity

| Input | Qualified value |
| --- | --- |
| Angular core/common/compiler/compiler-cli/platform-browser/platform-server | 22.1.6; full AOT, zoneless, server rendering and client hydration |
| TypeScript / Babel / esbuild / RxJS | 6.0.3 / 8.0.1 / 0.28.2 / 7.8.2 |
| Build Node / ComponentizeJS / jco | 24.19.0 / 0.22.0 / 1.34.0 |
| JavaScript guest engine | ComponentizeJS's packaged `starlingmonkey_embedding.wasm`, identified by its observed SHA-256 and npm integrity-locked inputs |
| Native execution | Wasmtime 47.0.4, Cranelift speed, on-demand allocation, fuel and epoch interruption, Component Model and async types enabled |
| Public application contract | `latent:web/application@0.1.0`, buffered V1, async `handle`; unchanged |
| Qualification-only interface | `lsf:renderer-qualification/renderer`, synchronous `render` plus adversarial `probe`; no imports |

The checked-in [profile](../../examples/renderer-profile/profile.json), npm lock
and source are versioned build inputs. Each build reports profile, package-lock,
embedding, server, client and resulting component digests. A build observation
is not signed provenance. #234 must bind actual observed materials to the
immutable package and existing SBOM/builder evidence model.

The retained repeated build failed byte-for-byte component reproducibility.
Identical recorded materials do not imply a predicted component digest. #234
must resolve or disclose the nondeterminism and reject a reproducibility claim;
every generated artifact remains independently content-addressed.

The installed adapter binds component digest, package identity, renderer profile digest,
adapter/host ABI, exact engine version and settings, target triple/CPU features,
security selection and native-artifact compatibility to preparation. Different
inputs cannot share an incompatible prepared entry. Shared code never carries
another publication's principal, capabilities or lifecycle generation; current
tenant/publication permission is rechecked separately at guarded activation start.

## Host surface and preparation

The fixture uses JavaScript language intrinsics, promises, typed arrays, Angular's
server DOM implementation, transfer state and the embedding's language-level
web utilities. It exposes no process, environment, filesystem, socket, entropy,
clock, HTTP or WASI import. Disabling clock imports does not establish useful
`Date`/`performance` semantics: applications requiring real time must use a
future explicitly mediated capability, not an ambient clock assumption.
The optional Angular `xhr2` dependency resolves to an explicit deny shim.
No Node built-in is externalized into the server bundle.

Bounded zero-delay `setTimeout(function, 0)` runs through the microtask queue;
at most 256 callbacks may be scheduled in one Store. `clearTimeout` cancels an
existing pending callback. String callbacks, positive delays, intervals and
interval clearing fail. Explicit `queueMicrotask` calls have a cumulative 4096
callback ceiling. Native Promise jobs are additionally bounded by Wasm fuel,
memory and epoch interruption; intercepting `queueMicrotask` alone would not
bound a Promise chain. No callback or queue survives Store destruction.
These restrictions are part of the profile and can reject otherwise valid
Angular dependencies that require timers or I/O.

Build/preparation must reject arbitrary package startup commands, dependency
lifecycle scripts, native addons, dynamic native loading, application listeners,
worker/process creation and unsupported built-ins. The fixture's browser-target
bundle and empty component linker establish its own closed imports. They do not
replace #234's production input/import validation for supplied applications.
Preparation must also verify exact public exports and component/profile/package
bindings before execution; it must never discover compatibility by running an
untrusted renderer inside the node.

ComponentizeJS 0.22.0 rejects direct async WIT export generation. The private
synchronous proof export drains JavaScript promises, and the selected production
direction uses the fixed async web adapter. Its required real-component gate
checks Wasmtime calls, finite cell ownership, cancellation and progress on the
shared Tokio executor. The private export must not leak into public SDKs. Any
required provider import must be explicit, brokered, granted, charged and tested;
the zero-I/O result does not prequalify provider-enabled Angular rendering.

## Ownership and measured limits

| Qualification bound | Value |
| --- | --- |
| Component input | 32 MiB before compilation |
| Linear memory | One memory, 256 MiB; observed growth/denials recorded |
| Core instances / tables / table elements | 32 / 4 / 131,072 per table |
| Wasm stack | 2 MiB |
| Guest fuel | 2,000,000,000 per ordinary probe/render |
| Host result lifting | 128 KiB Wasmtime hostcall-fuel ceiling |
| Epoch deadline | 5000 ticks with one owned approximately 1 ms ticker; wall-clock scheduling is not an exact timer guarantee |
| Adversarial interruption probes | 100,000 fuel or 25 epochs after instantiation, checked for the corresponding actual Wasmtime trap |

These are finite feasibility ceilings, not default latency/SLA recommendations.
One qualified render owns a fresh Store, JavaScript module globals, Angular
platform/injector/transfer state, memory and pending callbacks. The same compiled
component can prepare successive fresh Stores. Reusing a guest instance retains
its module counter in the negative control and is forbidden, even after a normal
Angular platform teardown. A failure discards the entire Store before the next
render; returning a timeout alone is insufficient.

The prototype holds one compiled component, creates one activation at a time,
and owns one epoch ticker that is stopped and joined. Its tracked Store-owner
count returns to zero after success and each failure. That counter is an
ownership observation, not a measurement of the allocator returning pages to
the OS. The limiter bounds linear memory/table growth, not whole-process RSS,
compiled code, input parsing, Wasmtime bookkeeping or embedder allocations.
The installed adapter uses the generic backend and node owners to account for
retained input/output, prepared images, aggregate concurrent memory, queues and
actual delivery owners. The table above records the original one-memory
qualification; the composed adapter has two memories sharing the same 256 MiB
aggregate ceiling, as specified in ADR-0040.

No dormant deployment owns a JavaScript engine instance, heap, process, thread,
listener, connection, event loop or timer. Only bounded immutable code and
metadata may remain in shared caches. Failed cleanup must conservatively retain
charges and quarantine the cell until it is safe to reuse.

## Candidate and security evaluation

| Candidate | T0 | T1 | T2/T3 |
| --- | --- | --- | --- |
| Closed Angular component | Executed controlled SSR/hydration and finite Store failure probes. Selected for adapter work. | Enabled only under explicit protected `external-capsule-v1` with enforced publisher/builder/SBOM admission, isolated compilation, authenticated native loading and sealed selected web authority. The [actual #226 T1 workflow](../testing/angular-t1-workflow.md), not the earlier T0 feasibility proof, qualifies this path. | Unsupported; no external guest process/stronger OS boundary is established. |
| Fixed node-owned Node compatibility slot | Real SSR, child interruption/reap and fresh-process reset measured. Retained module state and non-total heap limit remain constraints. Rejected for this first profile. | No implemented hostile-code process/filesystem/network boundary; rejected. | Unsupported and rejected. |

The Node experiment allows only one trusted child at a time. It executes two
requests in one process, repeats in a new child, kills and reaps a CPU loop, and
allocates a 64 MiB ArrayBuffer despite a 32 MiB V8 old-space limit. It does not
test an already-contained malicious Node host or disprove a future design.
Node's [permission model](https://nodejs.org/api/permissions.html) is not a
malicious-code sandbox; its [memory option](https://nodejs.org/api/cli.html#--max-old-space-sizesize-in-mib)
limits V8 old space, not all native/ArrayBuffer/process memory. A future native
host needs an explicit isolation profile, total process/resource bounds, fresh
request contexts and guaranteed process retirement before refunds.

Both candidates require independent compile/build containment for hostile
inputs. Compiler isolation cannot establish guest-host compromise containment.
The existing [execution security profiles](execution-security-profiles.md)
remain authoritative and reject unsupported selectors. None of this qualification
certifies production, hostile multitenancy or absence of engine/compiler defects.

See the [retained observations](../testing/angular-renderer-qualification.md)
for actual versioned evidence and limitations. #239 owns integrated release-build
performance; #235 owns browser defenses; #238 owns the integrated adversarial
matrix. No feasibility timing should be promoted into an infrastructure-wide
performance or density claim.
