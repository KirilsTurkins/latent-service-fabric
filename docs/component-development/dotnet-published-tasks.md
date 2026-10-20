# Published .NET retry and timer callers

The finite programme captures published `Polly:8.6.3` and its normal transitive
`Polly.Core:8.6.3` through the existing NuGet add, resolve and exact-review path.
It keeps both original archives, native package hashes, selected managed assets,
transitive edge and immutable SDK/compiler inputs. Neither package is modified,
registered as an eligible library or given an application scheduler/transport.
Normal resolution destroys its temporary package-manager workspace; compilation
uses only reviewed captured objects and the existing offline compiler path.

The application uses the ordinary legacy `Policy.Handle(...).WaitAndRetryAsync`
factory and the modern `ResiliencePipelineBuilder<int>().AddRetry(...).Build()`
factory. Their real default timers advance two failed attempts to a successful
third result. An incomplete completion-source gate makes the pending assertion
deterministic. Additional cases preserve the final original exception object
and the cancellation token while preventing another attempt after cancellation.
Every invocation must begin with fresh static state.

The same explicit CLOCK, ACTIVATION and RANDOM fixture authority used by the
ordinary task programme is required; there is no HTTP declaration or grant.
All original node assertions, provider-idle/physical observations, fuel/memory
limits, zero outbound/log/effect assertions and clean/reaped shutdown remain.

All four cases passed a separate SDK10.0.303 reference CLR programme. Four
source/graph/authority/oracle controls pass. **No signed guest result is claimed.**
The strict normal-native qualifier is prepared for the existing public normal
qualification bundle; maintained owning-job wiring and actual guest execution
must finish before delivery. This is a branch milestone while #1152's actual
task fix is executing, not a complete #746 qualification.

Polly identities and APIs: https://www.nuget.org/packages/Polly/8.6.3 and
https://github.com/App-vNext/Polly/tree/8.6.3 . The selected reference graph contains
only these two managed packages and no build hooks. Those reference assets are
not relabelled as the pinned NativeAOT resolver's selected closure.
