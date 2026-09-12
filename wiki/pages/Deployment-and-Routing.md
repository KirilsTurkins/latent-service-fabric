<!-- LSF-WIKI-MANAGED -->
# Deployment, routing and recovery

Deployments bind validated component releases to tenant-scoped routes. An atomic catalog publication changes desired state and the immutable route snapshot together. Existing calls retain their selected revision; new calls select from the newly published generation.

Object generation, route generation, catalog state version and rollout revision are separate identities. A package digest is also distinct from its component release digest. Do not substitute one identity for another in preconditions or recovery.

## Managed Apply and Delete

Managed operations bind an authenticated actor and tenant, operation ID, exact normalized request, expected object generation and expected global state version. Use GetDeployment's operation snapshot to read the object, or its absence, together with the catalog version. Generation zero means create only when the state precondition also matches.

Desired state, routes and a bounded operation receipt are committed in the same catalog publication. Exact retained replay is checked before compare-and-swap, including Delete after the object has disappeared. A changed request under the same operation ID is rejected. Legacy requests without an operation retain their documented compatibility behavior.

The default receipt ring retains 256 operations; the hard ceiling is 1,024. Unknown covers never-seen and evicted results. Uncertain means durable confirmation is unavailable. Neither result grants permission to invent a fresh retry. Read the original operation and current snapshot explicitly.

Complete success/rejection response preflight precedes critical audit and mutation. Critical audit begin is awaited before the synchronous commit seam; no await separates marking mutation started from that commit. Caller loss can leave an Unknown audit outcome beside an exact committed catalog receipt. Startup reconciliation matches the retained receipt and request identity before deciding an outcome.

## Rollouts and canaries

Manual rollouts use one bounded configured coordinator and the same audit owner. Start records a finite stage plan and the exact base/candidate association. Candidate manifest weight must equal the first declared stage. Pause, Resume, Abort and manual Advance require explicit operation IDs and expected revisions; none is an automatic controller.

A declared canary policy changes promotion authority. Evaluate returns diagnostics. Promote needs a sealed window from the configured owner bound to the exact revision, route generation, cohort, epoch and policy. The full observation interval must finish, entered captures and in-flight samples must drain, and coverage and minimum candidate samples must satisfy policy. Zero data, loss, abandoned samples, unsupported state or incomplete coverage cannot become healthy promotion authority.

Restart begins fresh observation. Historical counters and copied reports never mint proof. Exact retained operation replay remains available without collecting a replacement window. Registration pressure after a committed transition is reported separately and does not turn its receipt into a failed mutation. Resume can preserve weights while reporting unavailable observation when the canary owner is omitted.

## Explicit rollback and lifecycle changes

New Starts retain one immutable pre-Start rollback target in status. Read that target through GetRollout; it is not the resolved target field of a Start receipt. Legacy rows without the target remain readable/replayable, but fresh rollback is unavailable.

Rollback restores only that exact recorded target through a new route generation. The historical source can support structural comparison without granting execution permission. The target must independently pass current lifecycle, trust and runtime checks. A revoked target is never restored merely because it served before. Success is terminal and records the resolved target; there is no automatic rollback.

Release evidence renewal increments lifecycle authority for the exact retained package. Old deployment grants require fresh control compilation, including on restart. Route storage can remain historically visible while selection or final start is denied. Pausing or aborting a rollout does not bypass those checks.

Authorities: [deployment/routing](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/deployment-routing.md), [operator operations](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-2-operator-workflows.md), [rollouts](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-2-rollouts.md), [canary promotion](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-2-canary-promotion.md), [rollback](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-2-rollback.md).
