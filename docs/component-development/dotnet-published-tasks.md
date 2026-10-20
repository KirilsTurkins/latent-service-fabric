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

The same explicit CLOCK, WALL, ACTIVATION and RANDOM fixture authority used by the
ordinary task programme is required; there is no HTTP declaration or grant.
All original node assertions, provider-idle/physical observations, fuel/memory
limits, zero outbound/log/effect assertions and clean/reaped shutdown remain.

All four cases passed a separate SDK10.0.303 reference CLR programme. Four
source/graph/authority/oracle controls pass. **No signed guest result is claimed.**
The strict normal-native qualifier consumes this run's identity-checked public
normal qualification bundle. A separate 20-minute `published-tasks` job depends
on the existing normal .NET job; its original 75-minute parent commands and
bounds remain unchanged. Only the five binaries authenticated by the original
receipt have executable modes restored after artifact download. The source
controls preserve SDK inputs, the exact two-package graph, original budgets,
physical retirement and refusal of combined qualification selectors.

The first focused attempt stopped before package capture because its command
log directory had not been created; no component result is inferred. That setup
is corrected and a fresh signed campaign is running. The ordinary twelve-case
task programme is separately qualified in #1152; it does not establish these
published library cases or complete #746.

Polly identities and APIs: https://www.nuget.org/packages/Polly/8.6.3 and
https://github.com/App-vNext/Polly/tree/8.6.3 . The selected reference graph contains
only these two managed packages and no build hooks. Those reference assets are
not relabelled as the pinned NativeAOT resolver's selected closure.
