# Angular renderer qualification observation

Recorded 2026-09-15 for Phase 3 #224, based on development
`e9ac2b970e9f02c92ef45013ddacc44120d98a23` plus the qualification sources retained
with this report. This finite feasibility check is not a production benchmark,
security certification or completed node renderer adapter. The
[recipe](../../examples/renderer-profile/README.md) and
[profile](../runtime/angular-renderer-profile.md) describe reproduction and scope.

## Native SSR and browser hydration

Node 24.19.0 built actual Angular 22.1.6 full-AOT server/browser bundles on Windows.
Wasmtime 47.0.4 executed the component in an x86_64 Linux Docker container limited
to 2 CPUs and 2 GiB. The native host/Cranelift were debug builds; generated guest
code used Cranelift speed. The component was 23,773,029 bytes with no imports.

| Observation | Result |
| --- | --- |
| Cold native compilation, one debug-host sample | 197,067.648 ms |
| Fresh-Store SSR: Alice, Bob, Alice | 14.593 / 13.053 / 12.769 ms |
| Store setup for those samples | 6.531 / 0.224 / 0.182 ms |
| Guest instruction fuel | 55,321,659 / 54,736,023 / 55,321,659 |
| Observed linear memory per normal render | 21,233,664 bytes |
| Alice HTML / Bob HTML | 476 / 443 bytes, with hydration metadata |
| Reused-instance negative control | Module counter 1 then 2; fresh Stores always 1 |
| Store ownership after destruction | Zero after every success/failure |
| Actual native HTML in Chrome 152.0.7977.84 | Original heading DOM reused; escaped input preserved; Angular signal click works; no page errors |

These are individual observations, not medians or an LSF request budget. They
exclude admission, HTTP ingress, providers, delivery, competing workloads and
production native-cache behavior. Linear memory is not total activation cost,
process RSS or a density measurement. Compilation is outside invocation limits.

## Failure and recovery

Every failure is followed by successful Angular SSR with a fresh module counter.
Fuel, epoch, allocation and result-lifting checks require their actual cause,
not merely any failed call. The ticker is stopped and joined on exit.

| Probe | Actual outcome |
| --- | --- |
| 1 MiB instantiation limit | Memory limiter denied; owner released |
| CPU loop, 100,000 fuel | `OutOfFuel`, 0.761 ms |
| CPU loop / Promise storm, 25 epochs | `Interrupt`, 28.220 / 28.807 ms |
| Retained 4 MiB arrays | Memory growth denied; peak 264,306,688 bytes below the 256 MiB ceiling; 164.043 ms |
| JavaScript exception | Trapped; fresh SSR succeeded |
| 256 KiB result, instruction fuel remaining | Actual hostcall-fuel allocation rejection at 128 KiB; 342.458 ms |
| Positive-delay timer / interval | Trapped as unsupported |
| 257th timer / 4097th explicit microtask callback | Trapped at cumulative limits |

The output probe has a separate very large finite instruction-fuel allowance
and a 5000-epoch deadline, so an earlier CPU trap cannot masquerade as allocation
containment. Store-owner counters do not establish OS page reclamation or
compiler/whole-process memory containment.

## Alternative Node host and compiler limitations

The same bundle ran in one supervised Node child slot on Windows. Render samples
were 20.409/15.023 ms in one retained process and 22.877/13.321 ms in a fresh one.
The module counter was 1 then 2 in each process. Complete child lifetimes were
274.175/170.662 ms. A CPU-loop child was killed/reaped after 275.218 ms for a
250 ms parent timer. Peak owned children was one and final ownership was zero.

Despite `--max-old-space-size=32`, the memory probe allocated and filled a
67,108,864-byte ArrayBuffer, with 119,369,728-byte reported RSS. No hostile-code
OS containment was implemented for this candidate; it is not selected. Its
Windows timings cannot establish a speed comparison against Linux Wasmtime.

A minimal direct async WIT export failed in ComponentizeJS 0.22.0's splicer with
`not yet implemented` / `RuntimeError: unreachable` before Angular execution.
The private synchronous proof drains JavaScript promises. #233 still owns the
public async adapter and executable composition evidence.

Two additional builds with identical recorded profile, lock, embedding, server
and client digests produced different component bytes. Byte-for-byte component
reproducibility **failed**; the underlying cause was not established. #234 must
make it reproducible or explicitly report the limitation and reject a
reproducibility claim. Actual bytes continue to determine immutable package
identity. Do not normalize or substitute artifacts to match an earlier receipt.

| Identity | SHA-256 |
| --- | --- |
| Native-tested component | `036678e89f3872d562cf521c686fda369d06cb33b0be52f1b94cccc516ac99b4` |
| Profile | `f3f6e8c02eef8cf49643f318f0cd970738b815d4e545071d7efd97b3782400b2` |
| Locked npm input | `f3195990ed231efddcd792e735493ea0d75d9845beb3cbe54e06fd95a595f757` |
| StarlingMonkey embedding | `b45eb4dda2fed0eaecd4e5581fb26a99e642d001dbf82f3698aba27564a78ea1` |
| Server bundle | `60a147f076d2944ff8c5a34588bb48302fdcb1b7af4258797437e4063d35413f` |
| Client bundle | `d777fdd194e801b948ef23aab283ff513f48ca2117237adb321337302d34837c` |
| Repeated build A, 23,773,476 bytes | `752139a1ce25d1c3ea5d287665bec0bd8917d116e6958088164b06491474e148` |
| Repeated build B, 23,773,496 bytes | `e6bcc9f73836e0ee2d181bc4fc01d74cbafdc5a0a042a2af699d5fda11c7a392` |

The repeated-build artifacts are distinct from the native-tested artifact. CI
builds, hashes and tests its own artifact from the PR checkout. Git retains this
compact observation and source, not generated Wasm, bundles or timing archives.
