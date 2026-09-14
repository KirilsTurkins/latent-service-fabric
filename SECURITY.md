# Security Policy

LSF assumes capsule code, capsule inputs, remote invocation payloads, and external provider responses are untrusted unless an explicit policy says otherwise.

Security-sensitive reports should not be opened as public issues. Until a private disclosure channel is established, document the issue locally and contact the repository maintainers through a private GitHub security advisory.

The delivered Phase 1 trusted computing base includes the standalone node,
Wasmtime and its local compiler, local artifact/catalog verification, scoped
authentication and admission, activation capability hosts, and the host operating
system. The listener is restricted to authenticated local loopback operation.
Integrity verification of local artifacts does not establish publisher identity.

Phase 2 adds bounded OCI transport, package publisher signatures, independently
authorized builder provenance, SBOM policy, and enforced catalog admission.
Enforced mode checks complete package semantics and current tenant/trust policy,
with durable generation/clock floors and execution-time eligibility checks.
Declared runtime/target/CPU requirements must match the actual node profile.
Bounded [release comparison](docs/reference/release-compatibility.md) keeps
unsupported or unknown analysis from authorizing promotion; its reports remain
separate from live supply-chain authority.
Both local and enforced catalogs bind execution to their exact
[lifecycle owner](docs/reference/release-lifecycle.md). Durable revoke/retire
transitions cut off new route/preparation/start decisions; already accepted
activations may finish. Rejected uploads retain bounded operation outcomes and
cannot alter admitted content. Uncertain persistence denies positive eligibility.
Historical receipts and locally admitted flags do not grant current authority.
See [authenticated package admission](docs/reference/package-admission.md).

Phase 2 also delivers an opt-in authenticated same-node isolated AOT path on its
supported Linux x86_64 sandbox profile. Compilation runs in a bounded child and
persistent native reuse accepts only locally authenticated output bound to exact
engine, component and security configuration. The parent parser/validator,
standalone node, Wasmtime native loader and host OS remain trusted. This does not
support arbitrary external native artifacts and does not provide a separate guest
execution process. See [trusted AOT](docs/runtime/trusted-aot.md).

[ADR-0026](adr/0026-require-explicit-execution-isolation-profiles.md) and
[RFC-0001](rfcs/0001-minimum-execution-isolation-profiles.md) define the current
isolation-profile boundary. Fresh in-process Wasmtime stores remain the delivered
guest execution model. A stronger profile that must remain isolated after
compromise of the guest/provider/renderer process requires a separate fixed,
node-owned execution host and is unsupported until that backend and its finite
evidence are implemented. Security-profile selection must fail closed rather
than silently downgrade to a weaker boundary. The current trusted-local default
is for operator-controlled workloads. Linux x86_64 configuration loading now has
a descriptor-anchored protected-file policy for bearer credentials and enforced
trust policy. The explicit `external-capsule-v1` selector now requires enforced
admission, exact Phase 3 host ABI, the reviewed runtime and a supported approved
isolated compiler. `check-config` and startup verify those requirements; a
protected persisted marker prevents weakening the profile on ordinary restart.
Enforced admission alone still does not select compiler isolation. See
[execution profiles and their finite evidence](docs/runtime/execution-security-profiles.md)
and [protected configuration](docs/runtime/protected-configuration.md).

The optional [capability policy owner](docs/runtime/capability-policies.md) is now
part of the trusted computing base. It enforces closed rule parsing, tenant-scoped
revision/CAS history, protected storage and final policy/publication currentness.
Descriptive explanations and historical receipts grant no execution permission.
Uncertain persistence retires the live owner until verified reopen. Provider
installation and actual budget reservation remain separate broker boundaries.

The [asynchronous I/O ownership substrate](docs/runtime/async-host-io.md) retains
queue, running-work, buffer and stream charges through actual cleanup. It requires
a finite original Store deadline and checks authority after queueing. Cancellation
does not refund a blocking worker or retained consumer, and incomplete ownership
prevents cell reuse. This substrate does not install additional WASI providers.

General external capability providers, transactional state/effects, and cluster
mTLS remain later work. They add trust boundaries when implemented. See the
[security architecture](docs/architecture/security.md) and
[Phase 1 completion scope](docs/phase-1-completion.md). This remains an
experimental prerelease without a production security certification.
