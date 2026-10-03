# Canonical protected state startup

This source milestone connects the checked `state` settings to the actual
standalone startup and shutdown owners. It does not complete Phase 4
installation or qualification. The production caller currently accepts only an
empty operation list and empty tenant declarations; configured installations
fail before opening the business engine or accepting listeners. Their signed
selection, current policy and protected credential producers still need to be
composed through the original admission owners.

## Configuration boundary

The [state schema](../../schemas/node-state.schema.json) describes the closed
format-version-2 declaration. `storeIdentity`, `configurationEpoch`, an absolute
`checkpointRoot`, a startup timeout from one through sixty seconds, and each storage, native and
dispatcher partition are explicit. `createIfMissing` defaults to false.
Creation permits an engine leaf, never automatic parent-directory creation or
replacement of existing checkpoint data. Provision both private roots before
startup. The canonical business root is `dataDirectory/state`; the checkpoint
must be outside its actual retained ancestry, rather than merely a different
path string.

The Phase 4 budget profile and `state` settings must appear together. Enforced
supply-chain admission, durable audit and capability-policy ownership are also
required. State read/write ceilings and the effect count are explicit. Optional
Phase 3 ceilings allow separately installed stateless services on the same node;
the transactional manifest and admission owners still refuse immediate
child, outbound and blob grants. Configuration fields cannot grant continuity,
restore approval, caller authority or deferred execution permission.

The explicit bounded native profile used by the source fixtures has 128 ordinary
slots, a 256 MiB ordinary aggregate and a 64 MiB per-reservation ceiling. Recovery
has eight slots, a 96 MiB aggregate and a 32 MiB per-reservation ceiling. Derivation
checks the real initializer, validator, engine-resident and namespace-resident
footprints, plus separately usable headroom for a complete 32 MiB management
request. A larger engine cache needs corresponding explicit native capacity; no
fallback capacity owner or unlimited budget is installed.

## Ordered ownership

One empty effect-authority owner is created before artifact and policy exposure.
Both original catalogs attach its rejection-only observer before their first
read or mutation. Reusing preopened catalogs requires exact observer identity;
attaching a replacement after exposure is refused. No deferred rule is produced
from the descriptive configuration epoch, binding digest or credential name.

The original Recovery reservation exists before the initializer or resident
allocation. The [protected initializer](protected-state-root.md) delivers a
store already bound to that same native owner. A coherent bounded validation
checks supported producer codecs and cross-row ownership without repairing
counters or accepting unknown opaque records. Retained namespace metadata then
uses that original reservation.

The [private checkpoint](transaction-checkpoint.md) is opened and checked before
tenant preparation or dispatcher writes. Only the initializer's affine Fresh
witness permits missing-checkpoint creation. Reopening a matching identity,
caller flags or a restored old image cannot replace that evidence. The actual
supply-chain covered-clock source admits the effect clock; its provider
projection binds once to that exact returned clock.

Before the checkpoint consumes that witness, the same Recovery writer verifies
the fixed `STATE_OWNER_MODE` leaf inside the actual anchored business root.
Only retained Fresh metadata from the successful identity initialization, with
one coherent view still containing only that identity row, can create a missing
leaf. Existing bytes must match the closed format and store identity exactly;
malformed, interrupted or missing reopened markers are never
overwritten. Its actual file and native buffers retire on that same worker.

An omitted `state` declaration uses one temporary rejection-only owner after
acquiring the original artifact catalog's exclusive root. It checks the fixed
`dataDirectory/state` entry through retained directory handles and refuses any
existing file, directory or link there, or ambiguous ancestor ownership. This
read-only lookup never creates the business root, opens an engine, reads a mode
marker as authority or grants execution. Its Unix path does not impose the
protected engine's filesystem requirements on previously supported stateless
startup. The Windows path uses retained directory handles without a nightly
file-identity API; native platform qualification remains pending.

Before allocating its fixed worker or native path metadata, this probe reserves
2 MiB of actual Work capacity and one Recovery slot under the original clock
and a single thirty-second deadline. This temporary owner serves only the
rejection probe, not Phase 4 admission. The charge includes its 1 MiB worker
stack, bounded directory metadata and at most 640 KiB of retained path work.
The caller must close, finalize and join that one worker and retire its native
reservation before reporting stateless readiness. Cancellation keeps both the
original catalog's exclusive root ownership and the same prepaid capacity on
the live worker until its actual anchored descriptors are destroyed; it cannot
admit a replacement through an early catalog-lock release.

Exactly one dispatcher returns paused, with the same protected store, native
owner and early effect authority. The production caller retains the existing
`TransactionAdmissionOwners` factory. It checks the original deadline and current
clock/role before one readiness cutover; closing the actual role removes its
readiness without releasing engine residency. The empty bootstrap keeps dispatch
paused and installs no execution rule.

On failure, already-opened owners drain against the original boot deadline. A
dropped waiter cannot cancel native work or prove physical retirement. Normal
node shutdown first retires its effect scheduling/provider owners, then closes
namespace metadata and drains the engine, fixed storage workers and original
native capacity. A late owner remains quarantined and charged. The bounded
state shutdown report includes actual workers, callbacks, physical owners,
destructor backlog and native reservations; a pause or timeout is never a clean
retirement report.

## Qualification still required

The control producers now expose the actual persisted policy image generation,
the original charged secret generation for an exact HTTP or TLS credential
scope, and the exact selected signed `transaction-binding.json` asset. Policy
captures retain the finite read lease and original store owner; credential
captures retain the original zeroizing generation without exposing plaintext
through their metadata fence. Rotation, expiry, close, foreign owners and
uncertain state refuse the original capture rather than refreshing it.

The selected asset producer requires an existing Recovery reservation from the
same native capacity owner, with 24 MiB of Work and 2 MiB of Response prepaid
before source copying or filesystem reads. It reads at most 128 KiB of companion
data and 256 KiB per structural document, with a 4 MiB allocation-accounted
metadata parser. COMPLETE, the streamed component, package layout, metadata,
detached evidence associations and the original current signing/lifecycle grant
must all agree on the explicit selected publication. Other payloads are streamed;
the complete package is never copied into this response. Actual retained
capacities must fit the original Response allowance, whose permit follows the
owned result through destruction. The original full job reservation and slot
remain charged until its last worker/result owner drops, including after expiry.
An installation must acquire its own resident control retention before moving
these values out of their transient result; this API creates no additional quota,
execution rule or readiness approval.

Five policy-generation, five original credential-generation and six signed
companion schedules are additional registered source. The companion cases use
real Ed25519 publisher/provenance admission, including a payload larger than
the retained response, corruption, malformed or oversized declarations, exact
selection, expired or closed native ownership and physical last-owner retirement.
Their native compilation, discovery and execution remain required.

The source registers 53 additional `latentd` cases, retaining all 246 previous
cases and their ignore states. They include real protected-engine/checkpoint
startup, missing and malformed checkpoint recovery, same-owner factory admission,
one-time readiness, pre-I/O installation refusal, original-deadline refusal and
a paused native worker retaining capacity after failed drain. Registration and
formatting are not native test execution. Compilation, exact native discovery,
these schedules and strict Clippy remain pending under the shared compiler hold.
Eight additional native storage schedules cover marker initialization,
byte-exact reopen, premature business writes, missing/malformed refusal,
foreign capacity, expiry and a detached waiter retaining the original charge
until actual file retirement.
Nine additional stateless-startup schedules cover genuine absence, missing
parents without creation, existing entries, linked or replaced ancestors,
original expiry, and a detached waiter retaining actual catalog exclusivity
and native capacity. The actual local and observed catalog callers also refuse
omitted state settings before deployment or policy exposure. These schedules
are registered source; they have not been compiled or executed.

The focused schema checks cover closed owner declarations, finite counters,
immutable target pins, rejected authority flags and Phase 4 report identity.
They do not qualify the native runtime.

The remaining production work includes integrating the sealed signed-operation
and protected-credential captures into actual installation, their current policy publication
fence, original request/response integration with the Phase 4 wire runtime, and
bootstrap-pause release that preserves durable operator pause and restore review,
and native qualification of the stateless rejection probe on supported targets.
Those omissions are tracked explicitly; this milestone closes no Phase 4 issue.
