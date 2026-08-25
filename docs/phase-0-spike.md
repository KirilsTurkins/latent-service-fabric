# Phase 0 executable spike

`latentd phase0-spike invoke-once` is the finite composition root for the Phase 0 vertical slice. It is a local research and CI surface. It is **not production-ready**, does not expose a daemon listener, and is **not compatible with the future Phase 1 management or public invocation APIs**.

## One-command demonstration

After installing the pinned prerequisites in [`development/toolchain.md`](development/toolchain.md), run:

```bash
make phase0-spike-demo
```

The target validates repository contracts, builds the echo and containment guests, builds `latentd`, executes the end-to-end executable test, and finally invokes the real echo component. The last stdout line is the machine-readable invocation result. No external service is required.

Set a different demonstration input with:

```bash
LSF_SPIKE_INPUT='hello from a clean checkout' make phase0-spike-demo
```

## Direct invocation

The echo capsule builder stages `capsule.json` and the component under `target/capsules/echo/`. The capsule annotation identifies the component, so the generated directory is sufficient:

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

`--capsule` accepts either the generated directory or its `capsule.json`. `--component` overrides the `latent.dev/artifact` annotation when testing another local component with compatible capsule metadata.

Before reading or compiling the component, the executable validates scalar configuration, constructs a Tokio runtime with a fixed worker count, and constructs the immutable fixed-capacity cell pool from issue #20. It then:

1. reads and validates the local capsule and component digest;
2. creates the bounded Wasmtime engine and preparation cache from issue #21;
3. prepares the component without leasing a cell;
4. injects the fixed pool and contained backend into `Phase0ActivationRunner` from issue #22;
5. invokes one deterministic activation with a wall-clock deadline and optional cancellation signal;
6. captures bounded logs and the activation outcome;
7. releases or quarantines the affine cell according to backend cleanup evidence;
8. releases prepared state, flushes retained logs, stops the runtime, and reports the shutdown proof.

The process opens no listener or socket.

## Stdout contract

For an invocation attempt, stdout contains exactly one compact JSON object followed by a newline. Diagnostics and the non-production warning are written to stderr. The schema identifier is:

```text
latent.phase0.spike.result.v1
```

Stable top-level fields include:

- `activation_id`, `outcome`, `terminal_state`, `output`, and `error`;
- `elapsed_time_micros` and `consumption`;
- `cell.disposition` plus before/after fixed-pool observations;
- bounded `logs`;
- immutable `topology`, including worker, pool, and listener/socket counts;
- bounded preparation-cache observations;
- `shutdown`, including active leases, waiters, cancellation registrations, live Wasmtime resources, retained logs, and prepared entries.

A declared WIT domain error is represented by `outcome: "domain_error"` and `error.kind: "domain"`. Infrastructure failures use `error.kind: "platform"`. The echo output is UTF-8 by contract and is returned as `output.utf8`.

## Stable exit codes

| Code | Meaning |
| ---: | --- |
| `0` | Guest success |
| `10` | Declared guest domain error |
| `11` | Deadline timeout or explicit cancellation |
| `12` | Guest trap or guest resource interruption |
| `13` | Invalid component, capsule, or spike configuration |
| `14` | Internal composition or cleanup failure |

`--cancel-after-ms` is an explicit containment-validation mechanism. It shares exit code `11` with the wall-clock timeout while retaining `cancelled` versus `timeout` in the JSON outcome.

## Invariants checked at shutdown

A successful shutdown report requires all of the following to be zero: active leases, queued waiters, cancellation registrations, running invocations, retained bounded logs, prepared-cache entries, active backend invocations, live stores, live host states, live component instances, temporary buffers, and cancellation probes. `shutdown.clean` becomes true only after the Tokio runtime has stopped.
