# Native Windows capsule qualification

Issue #566's Windows x86-64 native test scope passed at candidate source
`0cb5cf08f1d7eb53650c116c93dcdd4c4a4d6bc3`. The
[retained observation](native-windows-qualification-observation.json) binds the
authenticated Windows archive, its native executable, the actual clean-host
schedule and the source-bound provider/differential receipts. The
[final qualification handoff](windows-qualification-handoff.md) supplies the
replacement package run and the complete platform, recovery and newcomer review.

The executable SHA-256 is
`c2aa294fef132428229cc417fe73945497610b2d7b829a3aafa079105a9d8453`.
It is identical in the approved package inventory and all twelve Windows
native provider, failure, comparison and language-application receipts from
[candidate build 36164649914](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36164649914).
Those source-bound tests remain labeled as such; their receipts do not claim a
clean installation or publisher authentication.

The Windows job in
[package run 36182234076](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36182234076/job/108227708298)
separately authenticated and installed the approved packages. It passed all six
language projects on WSL, stopped and purged the owned WSL distribution, verified
that it was no longer registered, then executed their compiled components using
the native Windows host. Node and native typed outcomes matched. The application
had no LSF checkout, host Python or host SDK on its PATH and did not build the
runtime. The separate conductor used Python. The runner reported Windows
`10.0.26100`, AMD64; the complete Windows schedule took 1,614.447 seconds.

## Acceptance evidence

| Requirement | Executed evidence |
| --- | --- |
| VM-free native components | Rust, C, Java, C#, Go and TypeScript run after the owned WSL distribution is purged; each native process is reaped. |
| Closed imports and typed values | Actual Rust and C components cover context, logs, clocks, random, metrics and buffered HTTP, including unsigned maximum values, absent results, declared errors and explicit capability denial. |
| Failure and fresh-state recovery | Actual trap, fuel, memory, deadline and prestart cancellation; fresh Store success follows failures. A fixed guest clock does not freeze host interruption. |
| Unsupported requirements | Unsupported imports reject before execution. Required Linux deployment and running cancellation stay unsupported and prevent native execution. |
| Real-node differential | Identical component/capsule/contracts bytes and typed results across WSL and native failure/clock cases; same-source enforced-node comparisons also cover HTTP, metrics and maximum clock values. |
| Resource cleanup | Native reports retain reusable invocation cleanup and reaped owned processes; HTTP verifies listener release, and metrics verifies exporter join and queue drain. |
| Distribution and dependencies | Independently approved candidate identity, offline verification, exact executable match, and the existing production dependency-boundary/CI inventory checks. |
| Explicit support and trust | The command requires portable selection and controlled-development consent. Receipts identify the host, ABI, component, fixtures and omitted Linux checks. |

The detailed observation retains SHA-256 identities for all original reports,
case selections, reviewed platform differences and six Windows/Linux native
tutorial comparisons. Node platform failures may use `resource-exhausted`
where the native engine identifies `fuel-exhausted` or `memory-exhausted`; only
the explicitly declared mapping is accepted. Deterministic payloads and artifact
bytes still compare exactly. System clock/entropy readings are not compared.

## Supported boundary

The qualified Windows environment uses `latent.dev.portable-request.v1`,
`lsf-host-abi-phase3-v4` and Wasmtime 47.0.4. It reuses production component,
canonical-value, capability and provider implementations with fresh invocation
state. The closed supported imports are context, log, monotonic/wall clock,
random, custom telemetry and buffered HTTP at the versions recorded in the
observation. Test fixtures are explicit and scoped; provider handles and exports
outside this profile remain unsupported.

This host executes controlled development workloads. It does not establish
Linux admission, deployment, authentication, protected files, PSI, compiler
isolation, native-cache behavior or production performance. Running cancellation
requires the real node; native cancellation-before-start is a different case.
Guest memory/fuel limits do not imply whole-process or compiler RSS containment.
Mac and ARM64 are outside the current epic scope.

Candidate approval permits these nonpublishing qualification runs. It is not a
public release, production-node approval or expansion of the supported security
profile. The earlier failed attempts remain linked in the observation, including
the original conductor comparison failure corrected by #596. The successful
Windows job does not relabel those failures or the separate devcontainer/newcomer
observations; their final results are recorded in the combined handoff.
