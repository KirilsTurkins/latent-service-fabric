<!-- LSF-WIKI-MANAGED -->
# Security and isolation

Execution permission comes from the configured catalog and current authority. A digest, cached file, caller-supplied publisher label or historical receipt cannot grant it.

| Boundary | Current enforcement |
| --- | --- |
| Management | Explicit authenticated loopback client; tenant/actor come from trusted identity, not a request field. |
| Package admission | Strict publisher signatures, independent builder authorization and configured SBOM association requirements. |
| Currentness | Policy/revocation generations, bounded trusted-clock leases and durable floors; invalid recovery state fails closed. |
| Lifecycle | Sealed exact-owner capability and generation checked through preparation and final invocation start. |
| Runtime compatibility | Actual engine/target/CPU profile; explicit unsupported or unknown requirements deny execution. |
| Guest isolation | Fresh Store and activation host state, finite budgets and no ambient WASI access. |
| Native reuse | Approved isolated compilation and locally authenticated exact native bytes; cache paths are never authority. |

Trusted-local mode retains explicit local compatibility. Enforced mode requires the configured policy and exact evidence; an initialized enforced catalog refuses downgrade. A valid but expired policy can permit historical status and restrictive management while granting no positive verification capability. Invalid policy, clock or durable-floor state aborts authority recovery.

Tenant-neutral local releases are an explicit trusted-host facility. Tenant RPCs neither reveal nor mutate them. Recovery renews authority through the existing bounded control owner; ordinary invocation checks remain immediate. A restart can be unavailable until the previous configured clock lease's durable future floor is reached.

Publisher and builder roles remain independent. Signature and provenance checks bind the exact package and component. A restricted in-toto statement describes the maintained observed recipe and bounded inputs; repository naming remains operator-asserted, and the build is lockfile-only and nonhermetic. This is not a SLSA conformance claim. SBOM associations describe inventory, not signer authority.

Revocation, retirement, policy changes and evidence renewal invalidate old capabilities. Renewed evidence does not replace component bytes; affected routes require fresh control compilation, including recovery. Prepared or queued work cannot turn an old token into a current one. Starts already accepted by the authority may finish under their existing ownership.

The implemented isolated compiler profile uses Linux x86_64, Landlock ABI 3 and seccomp. The parent authenticates the actual running approved executable before sending input; the child must establish the full sandbox before receiving untrusted component bytes. Unsupported or partial enforcement fails closed. This compiler isolation is distinct from a future isolated guest host or cluster trust protocol.

The optional native cache authenticates a receipt with a protected local host key, checks exact source/configuration/compiler identities and immutable native bytes, and rechecks current eligibility. It does not accept arbitrary native registry artifacts. Raw cache corruption may trigger one bounded refill; authoritative source, trust, deadline and resource errors remain failures.

Context, accepted logs and clocks are the delivered host capabilities. General network, filesystem, process, secrets, blobs and child calls remain denied until their Phase 3 implementations establish policy, ownership and accounting. See [State and effects](State-and-Effects) for later transactional guarantees.

For disclosure and supported boundaries, follow [SECURITY](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/SECURITY.md). Authorities: [publisher trust](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/reference/publisher-trust.md), [admission](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/reference/package-admission.md), [provenance](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/reference/build-provenance.md), [trusted AOT](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/runtime/trusted-aot.md).
