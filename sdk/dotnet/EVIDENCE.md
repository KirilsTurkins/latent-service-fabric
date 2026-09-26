# .NET transport qualification

The [native client](README.md) and its example are separate from the portable
contract model and from guest-language bindings. On 2026-09-19, Linux x86-64
validation used .NET SDK 8.0.425 and Microsoft.NETCore.App 8.0.31.

## Focused checks

`python3 sdk/dotnet/validate.py --check --osv` passed from two fresh, explicitly
bounded source snapshots. Each snapshot restored the locked NuGet graph from
the one configured official source, verified package signatures and selected
asset graphs, then regenerated seven C# files. Both generations matched the
committed source/tool/output hashes. Ambient Directory.Build/Packages imports
and shared build servers were disabled; no existing `bin` or `obj` was used.

The run passed 49 protobuf vectors, 521 native checks and 68 semantic cases,
with zero build warnings/errors. The controlled peer includes actual HTTP/2
reset/GOAWAY, malformed frames, oversized replies, duplicate fields/headers,
full-width unsigned values, cancelled/queued calls, audit uncertainty and
physical socket disposal. The fresh OSV query reported no affected package
coordinates; that observation is not a timeless security guarantee.

The four validator regression tests also pass. The shared security inventory
and graph suite passed 45 tests with one Windows-only environment skip; its
Linux execution remains an exact-head CI obligation.

## Actual provider node

The [machine-readable receipt](evidence/provider-workflow.json) binds the
transport source, integration source and exact executable/fixture identities.
The separate `latentd` used freshly signed maintained Rust HTTP/blob/callee
components. The language-native .NET participant passed all 18 assertions,
retained nine admitted activation IDs, made five authorized upstream requests
with no unexpected request, and observed four distinct held upstream sockets
physically close. The parent runner independently verified retained outcomes
and clean node/provider shutdown before reaping the process.

These are actual RPCs through `BoundedClient`, not a fake client, a CLI bridge
or another language's results. The operator CLI only stages the node's scoped
authorization and independently inspects its state. Policy replies currently
carry no audit acknowledgement, so the participant verifies absence rather
than inventing durability. Controlled peers separately exercise acknowledged
and uncertain mutations.

The shared runner and its maintained six-language CI matrix belong to
[PR #366](https://github.com/KirilsTurkins/latent-service-fabric/pull/366).
This local receipt alone does not complete that integration, prove the final
PR head passed CI, or qualify installed bundles, Windows, remote listeners or
browser clients. Keep #263 open until the maintained gate is merged and all
acceptance criteria are reconciled.
