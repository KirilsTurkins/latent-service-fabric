<!-- LSF-WIKI-MANAGED -->
# Getting started

LSF currently offers a finite local Phase 0 spike, not a daemon or deployment
platform. Start by validating a clean checkout and then run the real Component
Model echo path.

## Install the pinned toolchain

Follow the exact [toolchain guide](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/development/toolchain.md).
The validation baseline pins Rust, Component Model tools, Buf, Python, Go,
Node/TypeScript, Temurin Java, .NET, Zig, and the Zig C frontend.

From the repository root:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement tools/requirements.lock
make validate
```

`make validate` checks formatting, builds and tests the Rust workspace,
validates contracts/components, and verifies all supported SDK surfaces. It
does not start a network service.

## Run the local executable spike

```bash
make phase0-spike-demo
```

The target builds the echo and containment components, builds `latentd`,
exercises the executable E2E and containment suite, and emits one compact JSON
result for a real echo invocation. The process opens no listener or socket.

For a direct local invocation after building the capsule:

```bash
python3 tools/build_echo_capsule.py
cargo run --quiet --locked -p latentd -- \
  phase0-spike invoke-once \
  --capsule target/capsules/echo \
  --input 'hello through LSF' \
  --pool-capacity 2 \
  --pool-queue-capacity 16 \
  --runtime-workers 2 \
  --memory-bytes 4194304 \
  --fuel 1000000 \
  --timeout-ms 1000
```

Read the [Phase 0 spike reference](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-0-spike.md)
for JSON fields and stable exit codes.

## Understand the gate commands

```bash
# CI-sized correctness path; never Phase 1 authorization by itself.
make phase0-gate-smoke

# Full clean-checkout completion path; succeeds only with an authorized receipt.
make phase0-gate
```

The full command writes a receipt below `target/phase0-gate/`. Inspect
`gate-summary.json`; a real handoff requires `authorization_status` equal to
`authorized`, `phase1_authorized` equal to `true`, and no blockers. A blocked
receipt is useful diagnostic evidence, not a successful completion.

## Native-Linux evidence is separate

Calibration, CPU/allocation profiling, and long-running soak evidence are
heavyweight manual commands. They require a clean native Linux host or VM.
Their scripts reject WSL and containers as sources of new reference evidence.
See [Testing and benchmarks](Testing-and-Benchmarks) before attempting them.

## Next reading

- [Core concepts](Core-Concepts)
- [Phase 0 status](Phase-0-Status)
- [Capsule development](Capsule-Development)
- [Development workflow](Development-Workflow)
