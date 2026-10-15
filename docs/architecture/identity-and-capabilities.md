# Identity and capability architecture

The node authenticates configured bearer credentials on its loopback RPC
listener and applies tenant-scoped management, invocation, status and
cancellation authorization. Optional HTTP ingress uses its own explicit
principal mapping. Guest context, logging, clocks and installed provider
capabilities run under the current activation identity.

The [capability policy owner](../runtime/capability-policies.md) binds
immutable tenant policy revisions and provider selections to publication
eligibility. Sealed decisions receive a final currentness check; policy updates
and revocations invalidate held authority. The [broker](../runtime/capability-broker.md)
connects these decisions to activation-owned handles, budget charges and retained
work. The [binding compiler](../runtime/capability-bindings.md) publishes exact
host/local plans with deployment preconditions.

[Standalone configuration](../reference/standalone-providers.md) installs
buffered HTTP, local immutable blobs, activation clocks and OS-backed randomness
through explicit installations, bindings and grants. Other provider integrations
use their documented trusted Rust embedding. [Local child calls](../runtime/local-service-invocation.md)
derive a bounded service principal and conserve parent budgets; node workload
mTLS and remote delegation are not implemented.

The complete standalone inventory also includes explicitly configured streaming
HTTP, local secrets, custom metrics, local calls and immediate NATS publication.
S3 and Vault require trusted Rust embedding. Development TCP streams are separately
feature-gated. Use the provider reference for the accepted installation rather
than inferring availability from an import or a crate.

## Identity layers

LSF distinguishes:

- transport peer identity,
- authenticated caller principal,
- logical tenant and service identity,
- node workload identity,
- delegated child-call identity,
- administrator identity.

A local child call derives its service principal from the accepted parent and
checked binding. Root/parent IDs are correlation metadata and do not grant
authority. Planned remote calls must preserve that bounded delegation boundary.

## Broker authorization

Sealed decisions bind the trusted principal, exact operation/resource, service
revision, route generation, publication, current policies and installed provider
configuration. Policy ceilings narrow actual operation budgets; they do not
create a new ledger. Bind and call start both recheck currentness. No authority
fence crosses provider I/O or an await. [Capability audit](../runtime/capability-audit.md) records bounded decisions
without including credentials or payloads. Remote placement remains unsupported.

## Capability intersection

A guest import becomes usable only when requested by the immutable capsule, granted by deployment policy, and permitted for the current principal and operation.

## Broker handle properties

A handle is a slot/incarnation lookup inside one affine activation session. It
cannot transfer authority to another session or publication. Bind fixes the
operation and exact resource; every call rechecks current policy/provider
revisions and the effective deadline. Session termination invalidates lookup
slots, while actual provider work and result owners retain their charges until
destruction. Cell reuse requires cleanup proof. Descriptive DTOs, claims and
cached code are not grants. Local descendant delegation follows the checked target and conserved budget
contracts described in the local-call reference.

## Command and recovery authority

The installed transaction profile derives original command recovery scope from
the authenticated principal. Activation/root/parent IDs are not command keys.
Namespace administration, command admission, fresh-query read, original-result
read, effect inspection, dispatch and destructive recovery are purpose-specific
current decisions. Tenant equality, historical grants and original source pins
cannot substitute for any of them. A decoder publication supplies retained
source bytes without installing an operation or granting current business access.

The [transaction authorization owner](../../crates/latent-node/src/transaction_runtime/authorization.rs)
retains those checks through physical execution and final response delivery.
Protected recovery also needs its current operator/audit/clock and native fences;
a snapshot digest or proposed restore acknowledgement is descriptive input.
See [state management](../protocol/state-management.md) and
[protected recovery](protected-offline-recovery.md).

## Node identity

Planned node-to-node calls require mutually authenticated workload identity. Logical caller identity and node transport identity are carried and audited separately.
