# Original covered clock metadata

`SupplyChainAuthority::covered_clock_source()` returns a read-only carrier from
the original supply-chain owner. `CoveredClockSource::sample()` samples that
owner's exact `Arc<dyn SupplyChainClock>` once and returns the existing descriptive
`CoveredClock` fields: seconds, accepted authority epoch and covered-until seconds.
`is_from_authority` compares actual owner identity. Equivalent configuration,
historical receipts and a clock label cannot establish the same owner.

The carrier holds only a weak reference. It keeps no independent clock owner,
policy document, verifier, grant, filesystem lock or durable lease alive. It
performs no filesystem I/O, control renewal or callback into a policy/lifecycle
owner. The original trusted host clock remains responsible for a bounded sample.
The current admission, publication, namespace, provider and original cancellation
fences still govern work; this metadata grants none of those permissions.

An admission grant's `with_current` callback already holds the original
currentness mutex. Calling `covered_clock()` there reacquires the mutex and
returns busy. The carrier reads revision-stamped atomic metadata without
acquiring that mutex or the ledger. Its fields use sequentially consistent
publication and bounded reads. A revision change, partial publication or
completed concurrent observation rejects only that observation with the existing
`admission-authority-busy` reason. No reader spins, waits or borrows a cached
positive grant.

The accepted metadata changes only after the actual ledger persistence and
original post-synchronization validation complete. During a pending renewal,
readers retain the old covered ceiling. A replaced old ceiling is treated as
transient contention, including when it expired during the observation; it is
not evidence that the new accepted lease is uncovered. Every owner and carrier
sample contributes to one atomic observed high-water mark. A subsequent sample
behind that mark is clock regression. Existing owner paths keep the same clock
calls and durable floor format.

Carrier reads check the actual original retired, halted and poisoned state
before and after sampling. Durability uncertainty becomes visible even while an
existing grant owns its currentness mutex. Dropping or retiring the original
owner rejects its retained carriers; a newly opened owner never revives them.
The carrier does not clear regression or uncertainty in a held application
clock. `ProtectedEffectClock` must retain its original sticky rejection behavior
for those failures and preserve its original monotonic/wall-clock pair. Only
metadata contention is transient. Reading clock coverage cannot renew an
effect's original deadline, retry horizon, endpoint retention or expiry.

Ten Linux source schedules are registered for actual held admission grants,
all four ledger uncertainty cuts, accepted renewal visibility, shared regression
observations, retirement before ledger release, weak identity, policy epoch and
window replacement, and overlapping metadata/clock observations. Formatting and
source validators are separate from execution. Native tests and strict Clippy
for this addition are pending while the local disk limit holds compiler work.
Standalone protected-clock composition and held-provider qualification remain
separate acceptance work.
