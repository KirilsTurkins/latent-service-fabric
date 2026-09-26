# ADR-0037: Qualify a closed Angular Component Model renderer profile

## Status

Accepted; Phase 3 #224. Extends ADR-0002, ADR-0004, ADR-0006, ADR-0007,
ADR-0017, ADR-0026 and ADR-0035. This records the original renderer qualification.
The runtime adapter and observed builder subsequently delivered by #233/#234 are
described in [ADR-0040](0040-run-the-closed-angular-adapter-in-fresh-generic-stores.md).
The original measurements below retain their tested boundary; the
[integrated Angular workflow](../docs/testing/angular-reference-workflow.md)
records the later browser, provider and lifecycle checks.

## Context

An Angular package fixture does not establish executable Angular support.
Neither arbitrary Node applications nor a JavaScript engine's heap option meet
LSF's containment, ownership and dormant-resource requirements by themselves.
The application interface is async WIT; changing it to match one compiler's
current limitations would break the independently specified web contract.

## Decision

Select the closed `angular-ssr-component-v1` candidate demonstrated by the
[executable qualification fixture](../examples/renderer-profile/README.md):
Angular 22.1.6, full AOT and zoneless rendering, a bundled server module,
ComponentizeJS 0.22.0's StarlingMonkey embedding, and Wasmtime 47.0.4.
The package lock and embedding digest fix transitive build inputs. This first
candidate has no component imports or outbound I/O. It supports actual Angular
SSR, transfer state and client hydration within a fresh Store for every render.

The [profile contract](../docs/runtime/angular-renderer-profile.md) fixes the
qualified versions, preparation identity, limits, API exclusions, threat-model
evaluation and measured limitations. Positive-delay timers, intervals, native
addons, application listeners, lifecycle scripts and arbitrary `npm start`
applications are rejected. Bounded zero-delay callbacks run as microtasks;
this is an explicit compatibility restriction, not a general Node event loop.

ComponentizeJS 0.22.0 cannot generate the public async WIT export. The proof uses
a private synchronous export that drains JavaScript promises. Production #233
must place that operation behind the exact async `latent:web/application@0.1.0`
interface, with node-owned scheduling and cancellation. It must validate the
composition and forbid blocking the shared async executor. The private proof
interface and its adversarial export are not public SDK or capsule contracts.
An inability to meet this integration gate rejects the adapter; it never
silently changes the public interface or enables unrestricted Node hosting.

Prepared component/code caches are shared, finite and immutable. Their identity
includes component/package/profile, actual engine/target/configuration and host
ABI. They confer no tenant execution authority. Every activation owns a fresh
Store, JavaScript heap, Angular platform, module state and callback queues until
completion or interruption and destruction. No dormant deployment owns a
renderer instance, process, thread, timer, listener or event loop.

Reject the measured Node compatibility candidate for the first profile. One
fixed node-owned child slot can be supervised and reaped, but the tested host
retains module state across requests and its 32 MiB old-space limit permits a
64 MiB ArrayBuffer. No OS-level hostile-code boundary was implemented for it.
These results do not establish that a future bounded process-host design is
impossible; it requires its own #273 isolation profile and executable evidence.

## Consequences

The fixture qualifies operator-controlled T0 execution, not a production node
selector. T1 still requires enforced package admission, protected credentials,
isolated compilation, supported imports and the complete runtime adapter.
T2/T3 remain unsupported: compiler isolation is not guest process containment,
and Store memory limits do not bound whole-node RSS or embedder allocations.

The component contains a JavaScript engine and is approximately 23 MiB. Cold
preparation is substantial; the recorded debug-host compilation is not a release
compiler benchmark. Compiled-code reuse is justified, while persistent guest
state reuse is forbidden. #239 must measure the integrated release build before
making latency, density or capacity claims.

Repeated builds produced different component bytes with the same recorded
inputs. The recipe has not established byte-for-byte reproducibility. #234 must
resolve or explicitly report that limitation and reject unsupported
reproducibility claims while binding packages to actual generated content.

#225 must represent the renderer profile, immutable browser assets and exact
deployment selection. #233 owns current authorization, admission/preparation,
the async adapter, aggregate memory/cache/queue accounting, cancellation and
success-after-failure integration. #234 owns the observed bounded build recipe,
import validation, reproducibility claims, package/SBOM/provenance binding and
client/server separation. #235 owns browser security. The tiny fixture does not
claim those later deliverables, HTTP ingress or arbitrary Angular compatibility.
