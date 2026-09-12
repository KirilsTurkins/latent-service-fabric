# Security architecture

The current standalone boundary combines authenticated tenant management,
stateless Wasmtime containment and exact directory-catalog ownership. Phase 2
delivers enforced package admission, durable lifecycle, authenticated local
native reuse and control audit. Its [completion gate #158](https://github.com/KirilsTurkins/latent-service-fabric/issues/158)
remains pending; these features do not establish production readiness or a
multi-node security boundary.

## Untrusted inputs and authority

Capsule code, invocation payloads, tenant metadata, registry responses, detached
evidence, replaceable cache files and native output are untrusted inputs.
Validation, authentication and permission are separate checks. A content digest,
successful OCI transfer, public admitted flag, compatibility report or historical
receipt cannot grant execution authority.

The [management listener](../reference/standalone-node.md) authenticates explicit
credentials and derives the principal's tenant and actor. A request body cannot
choose another actor or tenant. Administrative release, deployment, rollout and
audit operations remain tenant scoped; node audit additionally requires the
trusted node-operator claim. That claim does not authorize arbitrary tenant
queries. The delivered listener is bounded loopback RPC; workload mTLS and
cross-node delegation belong to later work.

## Supply-chain admission

The [publisher verifier](../reference/publisher-trust.md) checks bounded Ed25519
signatures against approved raw keys, validity intervals and explicit revocations.
[Builder provenance](../reference/build-provenance.md) requires independently
approved builder keys and source policy. Publisher-only keys or a matching
referrer do not establish builder authority. The maintained build is nonhermetic;
its repository label remains an operator assertion. Certificates and keyless
signing are unsupported.

[Catalog admission](../reference/package-admission.md) combines those proofs with
exact package/component/tenant associations, supported WIT and manifest semantics,
SBOM content policy and the actual runtime requirements. Its deterministic
profile requires one publisher signature, one provenance envelope and zero or
one associated SBOM as policy permits. Durable policy-generation and clock floors
prevent rollback within the trusted storage boundary. Current authority is
rechecked at publication and final execution, independently of cache residency.

Explicit trusted-local mode remains available. It verifies immutable content
and lifecycle without fabricating package identity or signing proof. Enforced
configuration cannot downgrade to local permission because evidence expires or
is unavailable. A structurally valid expired policy can retain denied history
for management; invalid configuration, corrupt floors and tampered associations
remain fatal. An administrator replacing the entire node or approved trust
configuration is outside this local protection boundary.

## Lifecycle and execution cutover

[Lifecycle capabilities](../reference/release-lifecycle.md) bind the exact catalog
owner, scope, release and captured generation. In enforced mode they compose with
current admission proof. Raw preparation cannot bypass a configured owner.
Revocation and retirement preserve content but deny later use, including held
route, readiness and cache tokens. Only a call accepted at the shared final
start fence may finish after the cutover.

Renewed evidence applies to the same retained package and component. It commits
a new selected evidence revision and lifecycle generation without rewriting the
original completion record. Old in-process tokens do not upgrade. A fresh
control compilation, including startup recovery, may issue current capabilities
only for still-admitted content satisfying current policy and host requirements.
Rollback validates its target separately; it cannot restore revoked permission.

## Native compilation and loading

The default runtime compiles verified portable components locally. The opt-in
[isolated AOT path](../runtime/trusted-aot.md) supports Linux x86_64 with full
Landlock ABI 3 and seccomp enforcement. Before reading untrusted Wasm, the
approved one-job child has one thread, three directional pipes, finite hard
resource limits, parent-death protection and a default-deny syscall/filesystem
policy. It cannot create descendants, access the network or filesystem, or
create new executable mappings. Unsupported or partial enforcement fails closed.

The parent verifies the actual running executable, readiness profile, engine
fingerprint, exact bounded output framing, successful exit and fresh original
input eligibility. Reservations remain owned through cancellation, kill and
actual reap. There is no distributed compiler trust protocol or arbitrary native
fallback.

A protected host-local key authenticates receipts binding exact native bytes,
source metadata, compiler, engine, host and security configuration. Persistent
reuse authenticates the receipt before reading its claimed blob, then checks the
immutable byte lease before one private copying `Component::deserialize` call.
Replaceable files are never mapped through an unauthenticated file loader. Image
permits precede loading and outlive the associated compiled runtime. This local
MAC is not publisher provenance and does not replace current catalog authority.

## Guest capabilities

The current host exposes filtered context, structured logging and monotonic/wall
clocks. There is no unrestricted guest filesystem, socket, environment, process,
thread or secret access. General capability WIT declarations remain unavailable
until a concrete provider and its policy are implemented.

Phase 3's [broker and grant work](../roadmap.md#phase-3-capabilities-and-application-hosting)
will compose exact import requests, durable deployment/policy grants,
invocation-principal authorization and provider configuration epochs. Opaque
handles must be activation scoped, operation scoped, quota bound and revocable
without reviving stale handles. Descendant calls must conserve budgets and
cancellation ownership. Secret values must remain outside logs, audit fields,
cache keys, snapshots and derived artifacts. Shared pools and streaming I/O need
their own finite owners through cancellation and shutdown.

## Audit, recovery and storage trust

[Durable audit](../phase-2-audit.md) records closed typed observations, attempts
and conclusions without guest payloads, raw evidence, credentials, keys or private
paths. Its hash chain detects inconsistency within private current-UID storage;
it is not a MAC, external witness or protection against the owner rewriting the
whole journal. Diagnostic loss and prior-session uncertainty remain explicit.

Mutation response capacity is checked before critical audit acceptance and
catalog persistence. Exact committed receipts establish known outcomes; a
prospective receipt does not. A postcommit audit failure remains `OutcomeUnknown`,
not rollback. Revoke alone may proceed when audit capacity or availability fails,
while preserving authentication and the ordinary durable lifecycle transaction.

Catalog and cache recovery recognize bounded owned layouts, validate exact
associations and reject unsafe links or ambiguous history. An orphan complete
upload is not automatically admitted after lifecycle initialization. Caches may
reclaim only their replaceable unpinned bytes, never authoritative release data.
Lowered limits cannot silently discard security history to make room.

## Isolation scope

The delivered guest boundary is a fresh Wasmtime store in fixed in-process
cells. The compiler child is a separate bounded compilation boundary, not a
per-service execution host. Trust-sharded guest processes, native compatibility
hosts, containers/microVM fallback and separate-machine side-channel isolation
remain architectural options, not current execution modes. Phase 3 adds provider
and browser isolation tests; Phase 5 adds node identity and transport security.
