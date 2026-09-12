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
Historical receipts and locally admitted flags do not grant current authority.
See [authenticated package admission](docs/reference/package-admission.md).

Trusted external AOT loading remains planned Phase 2 work. General external
capability providers, transactional state/effects, and cluster mTLS remain later
phases. They add trust boundaries when implemented. See the
[security architecture](docs/architecture/security.md) and
[Phase 1 completion scope](docs/phase-1-completion.md). This remains an
experimental prerelease without a production security certification.
