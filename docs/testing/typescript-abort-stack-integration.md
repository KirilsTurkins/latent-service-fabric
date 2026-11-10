# AbortSignal stack integration

## Parent conflict resolution, 2026-11-10

The parent merge combines `feat/typescript-runtime-745` at
`99156cf7410dfcf2d07650fa95884ea280259d57` with `development` at
`110f6d0a30a20aa2514621b012c4e40aa1ddb2e9`. It retains both histories and
preserves unrelated development files. The stacked engine and Store-custody
changes remain separately reviewable in PRs #1934 and #1931.

The Fetch guest and runner had independently reused modes 27–29. Selecting one
side would silently omit either combinator ownership or AbortSignal fan-out.
The combined programme keeps combinator modes 27/28 and completed-capture
observation modes 29/30; fan-out, refusal/retry and default-factory reentry now
use 31/32/33. Fresh fan-out repeats 31 in a fresh activation. The finite Node
fault-injection fixture uses the same new dispatch modes. A regression rejects
duplicate dispatch arms, intersects probe-family modes, and executes the real
guest's ordinary combinator and fan-out arms under Node. This is probe-routing
reference evidence, not source-built SpiderMonkey qualification.

The timer merge preserves development's bounded round-robin ready-record
selection, as well as the parent's rooted-capture admission before host timer
creation and exact failed-retirement token retry. Captured-function and snapshot
controls from development coexist with parent native-owner retry/cancellation
controls. The record fixture retains matching throwing/nothrow allocation and
deallocation forms; no sanitizer suppression is added.

Both branches select the same `debug-all-features-v10` AOT feature closure. The
merge preserves that profile, not a new identity for equivalent inputs. The
signed runner retains both completed-capture diagnostics and the parent's
failure observations, rejected cleanup samples, and secondary evidence-write
errors. A case is completed only after its cleanup assertions succeed.

## Validation boundaries

On the locally reconstructed source projection with verified changed-file blob
identities, the focused parent selection passed 87 tests. The two additional
stack-routing tests passed. A final reduced pre-publication selection passed
47 tests, including both routing tests, emitted abort controls, native retry and
queue cancellation, Fetch refusal evidence and boundary controls. Counts describe
observed runs, not mandatory inventories.

The AOT input suite ran 17 tests: three passed and 14 failed at the required
process-containment prerequisite (`test-prerequisite-unavailable`) before the
artifact operations under test. No containment check was bypassed. The entire
combined development checkout, full repository suite, new signed component,
actual collector and original-activation Store/pool retirement are not qualified
by these local controls. Previously retained compiled engines are different
source identities and cannot stand in for this merge. Queued CI is not a pass.

No grants, native-owner ceiling, memory budget, deadline, expected signed result,
issue acceptance checkbox or API support claim is widened by conflict resolution.
