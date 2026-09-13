<!-- LSF-WIKI-MANAGED -->
# Frequently asked questions

**What is delivered now?** Phase 1, its performance extension and Phase 2 are complete. Phase 2 implements packages, signed admission/lifecycle, isolated AOT/native reuse, audit, rollouts, canary promotion, rollback and operator workflows. The [completion report](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-2-completion.md) retains the finite evidence and qualifications. These current implementation claims refer to development.

**Which release should I use for that surface?** The latest published release is 0.1.0-alpha.2, the Phase 1 snapshot. Alpha.3 is being prepared for Phase 2; until it is published, follow development for the completed features described here. A Wiki refresh is not a product release receipt, and planned Phase 3 capabilities are not part of this delivery claim.

**Does every dormant service have a process or heap?** No. Dormant services retain bounded metadata and artifacts. Execution cells, workers and pools are shared. Catalog RSS and storage can still grow with the number of releases.

**Does a valid signature mean a release is always callable?** No. Historical signature/admission results are separate from current policy, runtime compatibility, lifecycle generation and final-start eligibility.

**Can a cache authorize native execution?** No. Raw cache entries are storage only. Native reuse requires exact authenticated local compiler output and current source/authority checks; a filename or recomputed digest grants nothing.

**Can rollback restore a revoked release?** No. It uses an explicit recorded target, checks that target's current eligibility and publishes a new route generation. Historical compatibility input is not a grant.

**Does a healthy Evaluate response authorize promotion?** No. Promote requires the configured owner's sealed complete window and exact rollout/cohort/policy bindings. Zero data, loss and in-flight work cannot count as successful evidence.

**What should an operator do after a mutation timeout?** Look up the original operation with its original identity. Unknown and Uncertain are explicit limits; neither permits an automatic fresh retry. A committed catalog receipt and an Unknown audit outcome can coexist after caller loss.

**Are guest state and effects durable?** No. Phase 2 durable control records do not create transactional guest state, an outbox or exactly-once invocation effects.

**Are the SDKs full clients?** The six language surfaces have models and fixtures. The operator CLI has a concrete generated Rust transport; general SDK transports and provider helpers remain planned.

**Do the Docker/Kubernetes comparisons prove clustered LSF?** No. They compare actual local campaigns. Native was faster on warm headline calls; LSF used less dense-cohort leaf memory. Read the original limits in [Performance and infrastructure](Performance-and-Infrastructure).

**Is sub-2 ms latency a universal guarantee?** No. Historical percentiles, actual-deadline completion and different workloads establish different claims. No historical report is silently promoted to a current Phase 2 SLO.

**Does cancellation mean cleanup is complete?** No. Owners remain charged through actual retirement, child reaping and retained pins. Status acknowledgement is separate.

**What comes next?** Phase 3 is the next planned workstream, with [41 tickets](https://github.com/KirilsTurkins/latent-service-fabric/issues/201) for host capabilities, concrete providers, web hosting, SDKs and gates. Contracts, grants and shared ownership precede provider and web integration. Those tickets do not imply the functionality already exists.
