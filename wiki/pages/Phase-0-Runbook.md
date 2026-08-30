<!-- LSF-WIKI-MANAGED -->
# Phase 0 runbook

This is the operational reading guide for the executable spike and its
completion gate. It helps a contributor choose the right validation command;
it does not turn a local command into authorization by itself.

## Choose the right path

| Goal | Command | Meaning |
|---|---|---|
| Check ordinary repository health | <code>make validate</code> and <code>make repository-tests</code> | Required development baseline; no Phase 1 authorization. |
| Exercise the real local echo path | <code>make phase0-spike-demo</code> | Builds and runs the finite Wasmtime/cell-pool composition; no public service starts. |
| Exercise the CI-sized gate path | <code>make phase0-gate-smoke</code> | A deterministic correctness check that reports smoke success and authorization separately. |
| Verify or renew a Phase 0 handoff | <code>make phase0-gate</code> | Full clean-checkout sequence; only an explicitly authorized receipt can authorize its execution path. |
| Create new calibration/profile/soak evidence | Native-Linux evidence commands | Heavyweight manual work on a clean native Linux host or VM only. |

## Start from a clean checkout

Use the pinned [toolchain guide](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/development/toolchain.md)
and the repository’s current development branch. Install the Python tool
requirements before running the Make targets:

~~~bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement tools/requirements.lock
make validate
make repository-tests
~~~

The normal validation path exercises source, contracts, components, and SDK
surfaces. It is intentionally separate from the heavy completion workflow.

## Local executable demonstration

Use the demo after the baseline succeeds:

~~~bash
make phase0-spike-demo
~~~

It constructs the local echo Component Model fixture, prepares it through
Wasmtime, runs the finite containment path, and records its result. The
command has no daemon listener, release catalog, or public RPC compatibility
promise. See [Getting started](Getting-Started) for a direct invocation and
[Activation lifecycle](Activation-Lifecycle) for the ownership model.

## Full gate and receipt discipline

Run the full gate only when a clean checkout and the required retained evidence
are available:

~~~bash
make phase0-gate
~~~

The command writes a new receipt below <code>target/phase0-gate/</code>, even
when it exits non-zero. Read the receipt before changing documentation or issue
state:

1. Confirm that the authorization status is explicitly authorized.
2. Confirm that the Phase 1 authorization flag is true.
3. Confirm that the blockers list is empty.
4. Review source/execution identity and the regenerated raw-evidence results.

The retained August 30 native-Linux receipt meets these conditions for its
canonical execution identity. Do not treat it as applicable after an
execution-affecting change without a compatible full-gate result.

If any condition fails, preserve the receipt and address the named blocker.
Do not relabel an aggregate, close an issue, or use a smoke result as a
substitute. [Phase 0 status](Phase-0-Status) explains the evidence boundary in
more detail.

## Native-Linux evidence work

New calibration, CPU/allocation profiling, and resource-soak evidence requires
a clean native Linux host or VM. WSL and containers may be useful for code
development or gate validation, but the evidence scripts reject them as new
reference environments. Retain raw runs, host observations, manifests,
checksums, and the generated aggregate; never hand-edit a retained archive.

The authoritative process and current evidence ledger are in the
[completion-gate document](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-0-completion.md)
and [validation baseline](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/VALIDATION.md).

## When a result blocks

A blocked result is useful evidence, not a failed attempt to hide. Keep the
output, identify whether the blocker is environmental, raw-evidence,
identity/configuration, or fresh-baseline related, and make the smallest
reproducible correction. The gate is deliberately fail-closed so a missing,
stale, synthetic, or incompatible artifact cannot become an authorization by
narrative.
