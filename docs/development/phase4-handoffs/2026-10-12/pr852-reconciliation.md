# PR #852 reconciliation

PR: <https://github.com/KirilsTurkins/latent-service-fabric/pull/852>

The three preserved native preparation changes from `e0d03b14` are reconciled
with PR #851 at `cc440c89`, whose ancestry includes development `ab4e174c`.
The current source, native compilation, signing, cache and retirement owners
remain authoritative. This continues the chain through the most recent PR.

## Context and behavior

Read #707, #709 and #679, including their issue comments, alongside the existing
Phase4 acceptance context. #709 owns current-runtime preparation diagnosis;
#679 owns honest compatibility and lifecycle reporting. This native readiness
slice supports their currentness boundary and closes neither ticket.

Opt-in native readiness uses the same finite blocking-worker window as source
readiness for explicit native input, eligibility, cache-hit and linking
currentness rechecks. The window is minted once at the original job's creation;
queue time and later checks consume that same budget. Coalesced callers cannot
refresh it. Only the exact retryable currentness-busy diagnostic is retried.

The legacy entry remains nonblocking. Dropping or stopping the original job
terminates waiting and retains physical ownership until actual retirement.
Affine input acquisition, native compilation and native loading are not
replayed. Their own original fail-closed checks remain in place; this change
does not promise retries around an entire native producer or loader operation.

## Verification and acceptance boundary

The locked all-feature Wasmtime library suite passed 354 ordinary cases with
the two existing ignores retained. All 37 readiness cases and all 13 isolated
AOT catalog/compiler/negative-admission controls passed. The isolated AOT suite
does not load or invoke native output. Formatting and affected-library Clippy
passed with the 41 existing library warnings.

Hosted CI exposed a reserved-store test reading its counters after result
delivery but before the recovery worker's physical retirement. The test now
uses the existing bounded retirement observation while the ordinary reader,
writer and full queue stay blocked. The original `(1, 1)` assertion remains.

The original signed/current source and native owner tests retain their denial,
expiry, cancellation, coalescing, physical-capacity and destruction assertions.
These local tests do not establish #709's authenticated current-publisher input
owner or complete diagnostic programme, nor the six-language #679 matrix.
Historical unqualified WIP evidence is preserved and remains historical.
