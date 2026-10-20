# Random byte result retirement

The existing `system-random-v1` provider and `bytes` operation keep their explicit
RANDOM authority, cumulative byte allowance and sixteen live-call ceiling.
The host now owns each byte result in a concrete canonical-return wrapper.
The actual native byte allocation and original affine provider call survive
both generated lowering paths, guest realloc, destination checks and failure
unwind. The host buffer is wiped and freed before its original call charge
returns. Successfully copied guest bytes remain charged as guest memory.

The implementation delegates to the exact Wasmtime48.0.6 generated ABI.
`StaticHostFn::lower_result` owns the return value by value; generated list
lowering reallocates guest memory and copies the source before returning.
The private fixed-scalar completion trait remains closed. Other strings,
resources, retained list bindings and detached work keep their existing owners.

Previously each completed random byte result stayed in the Store-wide lowering
list. Sequential calls could exhaust simultaneous native-owner capacity even
after their host buffers had been copied and destroyed. The regression now
requires33 real sequential copies in each of two fresh invocations; the existing
sixteen-live-result negative holds the actual native buffers and still refuses
the seventeenth before entropy generation. Destination rejection, an actual
trapping guest realloc, provider failure/cancellation and fresh reuse remain
mandatory. No allowance is raised and no synthetic entropy is supplied.

The [actual native campaign](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39359322603/job/118421487525)
passed all15 original named random cases plus two new cases:17 passed, zero
failed/ignored/filtered. It built one ordinary normal host from the same frozen
`75b408ea0184936aa1dc21df2c9dd5e6c44bbc46` source for a separate published-library
experiment. Artifact12237197879 retains the raw test log, exact native source
archive, Cargo product/profile record and binary. The complete3295-file source
archive matches the frozen Git bytes; the host uses ordinary defaults, no extra
features, and retains debug assertions and overflow checks. Implicit compiler
inputs are not attested.

A byte-entropy capacity denial was retained during Polly8.6.3 `AddRetry`
diagnostics. The passing host controls do not establish that this fix qualifies
its modern pipeline; that exact four-case guest replay remains separate. No full
#681, #746 or #679 completion is claimed.
