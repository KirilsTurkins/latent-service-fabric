# Published .NET retry and timer callers

The finite programme captures unchanged `Polly:8.6.3` and its normal transitive
`Polly.Core:8.6.3` through the maintained NuGet add, resolve and exact-review path.
Original archives, native package hashes, selected managed assets and the
transitive edge remain captured. Offline compilation uses reviewed objects after
the temporary resolver workspace has been removed. There is no package-name
eligibility branch, application scheduler or transport injection.

All four ordinary factory cases passed signed NativeAOT execution in
[run39362050200](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39362050200/job/118430228859).
The [bounded observation](../testing/evidence/dotnet-published-tasks-signed-2026-10-20.json)
binds actual source `42e1d986fd725f32c2da73e4d0a954a01bdcad30`, component
`bbd5004e9663c30c5d970426448ef3f204237ad36efbd200fc6c9c6d8801b5d3`
and the two exact original package archives.

| Ordinary case | Observed result |
| --- | --- |
| Legacy `Policy.Handle(...).WaitAndRetryAsync` | Three attempts, two callbacks, value41 |
| Modern `ResiliencePipelineBuilder<int>().AddRetry(...).Build()` | Three attempts, two callbacks, value43 |
| Terminal failure | Original exception object, two attempts, one callback, value47 |
| Pending retry cancellation | Original cancellation, one attempt/callback, value53 |

The incomplete completion-source assertions, fresh static state, original fuel
and memory limits, zero outbound/log/effect requirements and explicit CLOCK,
WALL, ACTIVATION and RANDOM grants remain unchanged. All36 outcomes were known
and reaped, with28 complete physical samples and10 provider-idle observations.
Every published call retired its cells, queued work, quotas and activation owners;
node and peer shut down cleanly. Separate CLR reference results are not guest
qualification.

The selected ordinary host was compiled from frozen `75b408ea` and passed all17
random ownership tests. Earlier modern construction trapped after byte-entropy
capacity refusal; the native byte-result lifetime was corrected in #1170. The
fresh replay uses the exact four-case application, complete matching SDK/runtime
inputs and the same active runner programme. Differences in the final feature
are unused task-fixture data, two independently false runner selectors and
idempotent executable-mode restoration. Four helper binaries and companion builds
retain their authenticated historical03a provenance. This does not relabel them
as a current-head normal-native build or attest implicit compiler inputs.

The maintained20-minute owning job consumes this run's strict public normal
qualification bundle and preserves the existing75-minute parent and separate
scratch programme. Five focused controls preserve the graph, grants, budgets,
failed-row retention and physical retirement. No release is published.

This is partial #746 delivery. CPU preemption, full Thread/Monitor.Wait lifecycle,
logical ThreadLocal isolation, background-root drain, complete timer races and
the full resource/exhaustion matrix remain open.
