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

The focused native campaign runs all15 original named random cases plus two
new cases and builds one source-attributed normal host for a separate published
library experiment. Actual results are pending. A byte-entropy capacity denial
was retained during Polly8.6.3 `AddRetry` diagnostics; source inspection alone
does not establish that this fix qualifies its modern pipeline. No full #681,
#746 or #679 completion is claimed.
