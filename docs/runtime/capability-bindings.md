# Exact capability bindings

`latent_control_store::bindings` compiles checked capability bindings.
A trusted node composition supplies its catalog, sealed capability broker,
installed provider references and binding definitions. The compiler checks the
retained package WIT and publishes immutable plans with the existing deployment
catalog. A deployment, provider registration or policy document alone does not
authorize a guest call.

## Checked selection

A `BindingDefinition` contains the existing `BindingManifest`, an exact policy
provider-binding ID, explicit allowed physical modes and a closed deployment
restriction. Each actual consumer import must have one unambiguous definition
and one deployment capability grant. The grant's policy and operation narrowing
intersect the definition and installed provider restriction; uninterpreted legacy
constraint maps are rejected. Missing grants, multiple matching definitions or
providers, and another tenant's installation deny compilation.

Host selection validates the consumer's supplied WIT against the canonical
[host ABI](host-abi-profile.md). Isolated-local selection additionally validates
an exact provider deployment and its retained package export with the existing
bounded structural comparator. The fully qualified interface/version, complete
supported type definitions and dependency identities must match. The sealed
proof binds both package and component identities. Current package import
recognition remains the canonical host capability surface; this does not enable
arbitrary imports, type adapters, unsupported resources, futures or streams.
The descriptor-only `BoundedBindingCompiler` likewise denies named types whose
definitions cannot be established and does not trust caller-supplied digest labels.

Only `host` and `isolated-local` compile. `auto` searches only the explicitly
allowed modes and rejects ambiguity; it never widens the list. `inline` and
`remote` are unsupported. Local edges, including possible local `auto` edges,
undergo bounded cycle and depth checking. The compiler pins the provider's exact
publication, revision and deployment identity rather than selecting it again
from a mutable service route at call time.

The [local service invocation profile](local-service-invocation.md) explicitly
binds canonical `latent:service/invoke@0.1.0` to one checked application export.
It separately proves both surfaces and limits dispatch to the pinned target's
function table. This adapter uses explicit `isolated-local` mode, requires an
exact service/publication policy and supports authorized cross-tenant targets.
It does not relax equality for other direct bindings. The configured graph uses
the actual target tenant when checking cycles and depth.

## Publication and live authority

`prepare_binding_update` captures the existing route generation and control
transaction version. It holds the shared control-work permit while compiling a
tentative catalog. `commit_binding_update` consumes an affine, store-owned
prepared update through the normal catalog CAS. Policy/configuration and provider
installation fences cover final publication; route, rollout and binding changes
cannot commit through independent journals. A conflicting manual route update
wins over an older prepared binding update. Ordinary deployment/rollout updates
recompile inherited desired bindings in that same catalog transaction.

`CapabilityPlanSource` on the deployment repository returns a sealed plan only
for the exact tenant, service, revision, component, publication and pinned route
generation. Old route pins can retain their original plan data within a finite
weak-generation index. Policy/configuration changes, provider retirement or
publication revocation still deny new use. A local provider deployment removal
or revision/publication change also invalidates its older plans. Desired binding
history remains available when a provider becomes unavailable.

Both bind and final call start hold the local-route fence and recheck the
consumer and selected provider publication inside the same catalog admission fence. This
supports non-reentrant publisher authorities. No start fence crosses provider
I/O or an await. Work accepted before cutover retains its original resource and
cleanup ownership. `ProviderCall::local_target` exposes the exact compiled target
and the handle's operation to the trusted local adapter; the returned descriptor
is not an independent grant. [Descendant admission](descendant-budgets.md) and
[guest local invocation](local-service-invocation.md) include fresh child
eligibility and prompt rejection under fixed-cell saturation.

The generic `RouteSnapshot.bindings` projection and legacy `resolve_binding`
interface remain descriptive/unavailable: they cannot express this operation's
sealed authority. Live plans reside in the same internal immutable catalog as
routes. [Standalone provider configuration](../reference/standalone-providers.md)
installs the selected HTTP, local-blob, `clockMonotonic`, `clockWall` and `random`
providers and their host bindings. Other provider installations and
isolated-local target bindings use trusted Rust composition. These opt-in
installations still require exact deployment grants and current policy;
enabling policy CRUD alone does not install plans or capabilities.

## Recovery and bounds

Desired definitions use optional `capability_bindings` inside the existing
checksummed `catalog.json` envelope. Nonempty definitions select format 6 unless
HTTP route state selects format 7; catalogs with neither use format 5. The current
node accepts these three formats and rejects obsolete formats 1 through 4 with
`unsupported-catalog-format-use-fresh-state`. Recovery validates the retained
definitions but restores no live provider references or grants. The trusted node
must explicitly recompile and commit them against its current policy owner and
installations before use.

Defaults cap definitions at 256, deployed binding plans at 128, installed
provider facts at 128, graph depth at 16, retained generations at 16, each
definition at 64 KiB, one package at 32 MiB and binding source metadata at 8 MiB.
Operators may lower these limits. Graph work is capped at 131,072 edge visits
and compilation has a 30-second deadline. The broker separately reserves shared
plan and metadata capacity, with at most eleven capability imports/local targets
per plan. Current and tentative plans both consume that capacity; retained pins
may cause a bounded update rejection until their owners release them. Replacement
compiles one tentative set, leaving room under the default 256-plan broker limit.

Plans retain metadata and eligibility only. No guest Store, component parser,
provider connection, cell, service task or per-service pool is created. Shared
[provider pools](provider-pools.md) materialize work only through accepted calls.

## Validation

The control-store tests use actual checked packages and catalog publications
with a test admission authority. They cover host/local selection, version and
mode denial, ambiguity, cross-tenant denial, policy/route races, provider removal
and revocation, retained-generation and plan capacity, restart and independent
tenant admissions of identical Wasm. The final-start test uses an authority that
rejects recursive fence acquisition. Broker tests verify that a stale local route
cannot enter a provider constructor through a previously issued handle. These
are binding/admission tests, not guest nested-invocation or production containment
claims; those require their own adapter and conformance tests.
