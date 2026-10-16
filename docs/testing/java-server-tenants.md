# Shared-node Java tenant isolation

This candidate qualifies one ordinary Java `HttpServer` application under two
independently admitted tenant publications on the same node. Native execution
is pending the maintained Linux job. Source controls and JDK API compilation
alone do not establish isolation.

The first hosted candidate compiled and validated the actual Java component,
then failed at package assembly before signing or invocation. The fixture had
removed its tenant but retained an `examples/` service prefix, contrary to the
existing manifest scope rule. The corrected fixture uses an unqualified service
name; the manifest validator is unchanged. A metadata regression uses the real
shared emitter, while the next run also retains the previously omitted packager
stderr. The [original failure](evidence/java-server-tenants-package-failed-2026-10-16.json)
does not establish tenant isolation or a signed pass.

The normal project creator, compiler, package builder and fresh-store runtime
remain in use. The application adds an ordinary helper that retains a request
marker, a byte array and a static call counter. Alternating successful HTTPS
requests from both tenants must each see initial state and return only their
own marker and bytes. Actual activation roots and resolved release, revision
and catalog metadata must belong to the requesting tenant. Each tenant is
denied access to the other's retained activation metadata.

The fixture uses one tenant-neutral signed package. A dedicated test-only signer
accepts exactly one observed neutral Java server build and explicitly authorizes
the two fixture tenants. It checks both with the normal supply-chain verifier;
keys remain ephemeral. Ordinary `demo-sign` retains its examples-tenant boundary.
Each tenant publishes the exact same package bytes through its authenticated CLI
and creates its own deployment and trigger catalog. Operator deployment metadata
selects the tenant without changing the signed package or captured build.

Explicit [scalar aliases](../reference/standalone-providers.md) reuse the same
clock and context registrations. Examples-tenant policies must not authorize the
foreign publication: its first request must be rejected before guest execution.
The ordinary admission path may reserve one cell lease before validating the
revision's capability session. The control identifies the original foreign
activation and resolved revision, requires the exact permission-denied rejection
and zero guest fuel, memory and other work consumption, then verifies physical
retirement. It permits at most one original lease and no new cell class. Ingress
route and credential refusals retain their separate no-cell assertions. Only
separate exact provider-binding policies, trigger principals, publication policies
and deployment grants permit positive foreign requests. An operator token from
the wrong tenant cannot select foreign control resources, and an operator bearer
token does not authorize an HTTP handler.

The [retained first execution](evidence/java-server-tenants-runtime-grant-boundary-2026-10-16.json)
returned the expected foreign HTTP 403 but failed the earlier blanket no-cell
assertion. That source-bound record distinguishes the observed lease increase
from the before-Store refusal established by source inspection. A fresh hosted
foreign activation receipt is still required; the examples-tenant zero-work
receipt does not substitute for it.

The programme retains the original one-cell, queue, audit and provider ceilings,
the 64 MiB application limit, one billion fuel and 120-second guest deadline.
Every HTTP outcome requires the original physical idle observations. Triggers
are removed through their exact scoped control owners; the actual node must
stop cleanly and its process must be reaped. Topology completeness is reported
as observed; these bounded owner measurements do not imply a global process audit.

The existing 52-case ingress and 12-case revision lifecycle programmes stay
unchanged and run first. The separate two-tenant programme reuses their five
captured default native products and the existing read-only Java compiler cache.
It retains source, compiler, package, control, HTTP and shutdown evidence and
checks those input identities again. It remains a slice of
[#728](https://github.com/KirilsTurkins/latent-service-fabric/issues/728).
