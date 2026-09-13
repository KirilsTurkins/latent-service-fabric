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

[ADR-0025](adr/0025-require-explicit-execution-isolation-profiles.md) and
[RFC-0001](rfcs/0001-minimum-execution-isolation-profiles.md) define the current
isolation-profile boundary. Fresh in-process Wasmtime stores remain the delivered
guest execution model. A stronger profile that must remain isolated after
compromise of the guest/provider/renderer process requires a separate fixed,
node-owned execution host and is unsupported until that backend and its finite
evidence are implemented. Security-profile selection must fail closed rather
than silently downgrade to a weaker boundary.

General external capability providers, transactional state/effects, and cluster
mTLS remain later work. They add trust boundaries when implemented. See the
[security architecture](docs/architecture/security.md) and
[Phase 1 completion scope](docs/phase-1-completion.md). This remains an
experimental prerelease without a production security certification.
