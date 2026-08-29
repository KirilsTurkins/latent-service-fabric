<!-- LSF-WIKI-MANAGED -->
# FAQ

## Is a service a process in LSF?

No. A service is logical identity, immutable artifact metadata, policy, and
route information. An invocation temporarily leases a generic execution cell.

## Is LSF production-ready today?

No. The repository has a narrow Phase 0 local spike. It does not provide the
Phase 1 public node, management, routing, deployment, or production-security
surface.

## Is Phase 0 complete because issue #25 is closed?

No. The authoritative condition is a clean-checkout full-gate receipt with
`authorization_status: "authorized"`. Administrative issue state is not a
substitute for that evidence.

## Does a smoke gate pass authorize Phase 1?

No. `make phase0-gate-smoke` validates a smaller deterministic path and
reports authorization separately. Only `make phase0-gate` can require an
authorized receipt.

## Can WSL create new Phase 0 calibration, profiling, or soak evidence?

No. WSL can be useful for development and gate validation, but the native
evidence scripts reject WSL and containers as new reference environments.
Use a clean native Linux host or VM.

## What does the Phase 0 spike prove?

It proves a bounded, local real Component Model echo path through Wasmtime,
fixed cells, containment/recovery exercises, and documented measurement
evidence for its recorded configuration. It does not prove a production fabric.

## Are the checked-in Protobuf services already live APIs?

No. They are authoritative contracts and planned surfaces. An implemented,
validated public runtime behind them is later work.

## Why can a cell be quarantined instead of reused?

Reuse is allowed only after cleanup is explicitly proved safe. Quarantine is a
conservative response when the runtime cannot establish that state is clean.

## Does the native-Linux soak prove no leaks forever?

No. It records a bounded plateau for its selected host/configuration and
duration. It does not establish arbitrary-duration leak freedom or a
production SLO.

## Where should I look for the current truth?

Start with [Phase 0 status](Phase-0-Status), then consult the linked
`development`-branch documentation, raw evidence, receipt, and issues.
