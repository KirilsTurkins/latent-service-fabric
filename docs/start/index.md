# Start with LSF

## Outcome

Choose an appropriate way to try one standalone node, then follow a capsule from
source to a retained invocation and controlled recovery. You do not need to read
the phase history before starting.

LSF runs stateless WebAssembly components on demand. A dormant deployment has
catalog/routing metadata, but not its own process, listener, thread or guest heap.
The node still has fixed workers and bounded shared catalogs/caches, and active
calls consume execution resources. This is an ownership model, not a promise of
zero idle memory or a hardware-independent memory saving. See the
[resource model](../runtime/resource-budgets.md) and
[measured evidence boundaries](../testing/benchmark-retention.md).

## Supported version and prerequisites

These are **development** guides. Use a clean checkout of the exact reviewed
source you intend to build; record that commit with the resulting artifacts.
A guide rendered successfully is not evidence that those artifacts ran.
The [installation status](../installation.md) distinguishes tested native
candidates from a publisher-authenticated binary release. The historical
alpha.3 channel is source-only; do not assume a candidate download is an approved
release or reuse an old release's evidence for development binaries.

| Your goal | Follow this path | What it does not do |
| --- | --- | --- |
| Try the source as a contributor | [First node and retained invocation](first-node.md), with the pinned Rust/Python/contract tools and Linux pressure observations | It does not install a system service or download a trusted runtime bundle. |
| Evaluate an independently approved native bundle without root | [Bundled rootless evaluation](../../packaging/linux/INSTALL.md#rootless-evaluation), after the [independent bootstrap trust checks](../../packaging/linux/INSTALL.md#prerequisites-and-independent-bootstrap-trust) | It does not turn an unsigned candidate into a release or require a local compiler. |
| Keep a native node on a server | [Persistent installation](../../packaging/linux/INSTALL.md#persistent-server), under the installer owner's supported host matrix and explicit security profile | It does not require Docker/Kubernetes, open public management, or approve a binary downgrade. |

The source exercise uses `local-experimental-v1` and `trusted-local` admission
only for the echo guest built by the same trusted contributor. Do not use it for
untrusted third-party capsules. `external-capsule-v1` requires its own enforced
admission, protected configuration and approved isolated compiler. An unavailable
profile is a reason to stop, not to remove the selector. Neither profile is a
claim of production or hostile-multitenant certification. Read the
[profile contract](../runtime/execution-security-profiles.md) before changing it.

## Learning sequence

Start with [one node](first-node.md): protected random credentials, configuration
validation, authenticated readiness, publish/deploy/invoke, declared failure,
retained deployment after restart and bounded shutdown. Then
[author a capsule](../learn/author-your-first-capsule.md), using the actual Rust
echo implementation and its WIT contract rather than a pasted pseudo-SDK.

Continue to [trusted delivery and recovery](../learn/deliver-and-recover-a-capsule.md)
for packages, signing, provenance, SBOM, registry transfer, publication,
managed preconditions, canary promotion, rollback and uncertain receipts.
Its disposable registry is a **test fixture**; a container runtime is not an LSF
installation requirement. That guide pins its own source and retained evidence;
do not mix its historical checkout with binaries built by the first-node path.

Use [operate and contribute](../how-to/operate-and-contribute.md) when diagnosing
readiness, overload, deadlines, cancellation or choosing a focused contribution.
Each path links its complete source, expected results, failure cases, cleanup and
validation limits. The [coverage inventory](../../website/content/coverage.json)
tracks these outcomes without treating page existence as acceptance.

## Failure, cleanup and next step

A missing binary, unavailable toolchain or unsupported host is a prerequisite
failure. Resolve the documented prerequisite; do not substitute an unreviewed
installer, disable authentication, enlarge product limits or replay a mutation.
The first-node runner owns and removes its temporary node/client state. Native
removal and separately confirmed destructive purge belong to the
[bundled lifecycle instructions](../../packaging/linux/INSTALL.md#removal-and-separately-confirmed-purge).

Transactional guest state, durable workflows, a transactional outbox and
cluster-wide routing remain separate later-phase work in the [roadmap](../roadmap.md).
A blob or event capability does not make those semantics available.

Next: [run your first node](first-node.md). The
[guide validation record](../development/core-guide-validation.md) states exactly
which checks are executable and which runtime or human reviews remain required.
