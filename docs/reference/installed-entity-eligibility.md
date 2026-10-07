# Installed entity command eligibility

The protected `StateRuntime` owns one finite `EntityCommandLanes` table. Every
installed `CommandCoordinator` receives that same table directly, bound to the
runtime's actual protected store. Configuration may select tighter finite queue,
key, active-owner, byte and wait-age limits; the existing 64 KiB node configuration
limit and the original ingress/native capacity limits still apply.

The normal installed `CommandAdmissionFactory` selects and seals the current
caller, publication, namespace and result policy. Admission publishes the actual
durable Pending command before enqueueing its claimed entity identity. The
identity includes tenant, namespace incarnation, entity, canonical command digest,
attempt and original role epoch. A duplicate uses the existing authorized lookup
path before entity enqueueing. A transactional child refuses before selection
and claim publication.

Eligibility precedes post-claim native reading, guest view creation and scheduler
cell admission. The existing accepted activation future drives a single shared
wake notification and its original deadline; keys own no tasks or timers. Ready
dispatch rechecks captured/current authority. The post-claim namespace read then
uses the actual store and preserves the original captured deadline when it seals
the execution host.

An actual lane owner fills the once-only keeper in the original pre-Pending
protected operation. Its physical clones travel with the real post-claim read,
retained view, host operation, writer and abort/cleanup work. Cancellation removes
queued work and retires its original claim through the existing coordinator.
Dropping a waiter, host observation or response cannot release a live worker's
lane. Unexpected operation loss retains the existing bounded quarantine keeper.
Only positive native retirement permits physical release and empty-key reclamation.

Final acceptance holds the short entity fence through the existing captured and
current policy, namespace, effect and cancellation checks. The original native
request and command-role acceptance fence remains outside that sequence. The
entity lock covers no storage I/O or await. Dispatch checks authority outside the
entity lock. A retained fence observation grants no physical ownership or commit
authority after retirement.

The internal coordinator schedules exercise two real policy-sealing factories
on one protected store: hot-key waiting before a guest view, cold-key progress,
original registered cancellation, queued policy revocation, detached physical
reader retirement, actual transport interruption, accepted commit and final
cancellation refusal. Transport interruption observes the original node-owned
stop signal through sealed admission control and routes the still-owned Pending
claim and operation through existing abort cleanup. It does not install an
explicit cancellation winner or infer retirement from a dropped future. A separate
startup schedule opens the actual installed `StateRuntime` and checks that its
coordinators retain the one existing table without admitting a request. These
schedules preserve the five-second worker barriers and ten-second activation
ceiling of the original common-owner schedules.

These native schedules do not establish signed packaged activation, actual
broker/node delivery, hosted CI, or complete Phase 4 issue acceptance. Those
composition and qualification gates require separate current execution evidence.
