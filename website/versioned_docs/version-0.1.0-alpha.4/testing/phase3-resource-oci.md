# OCI pool resource qualification

The manual OCI campaign passed on source `4273942ac2c6a7d995a3a2ae99ff8a178cafeee6` on 21 September 2026 (local date). The [execution receipt](phase3-resource-evidence/2026-09-21-oci-run-05.json) binds the exact Cargo-reported test executable, compiler, source inputs, configured limits and all four reaped commands. The [48 observations](phase3-resource-evidence/2026-09-21-oci-observations-05.json) have an independent SHA-256 sidecar. The executable was 24,526,128 bytes with digest `sha256:3f4f84f3cfeb1d5b3a2a3ba20fed493dabe3b8f90d29b7eb6792867e1b681f4c`.

This was a shared Docker Desktop/WSL2 Linux host with three CPUs and 6 GiB. One current-thread Tokio runtime owned the registry client and real local TLS/DNS protocol peers. The process snapshot includes the test harness and peer costs; it is not a standalone registry or production-network throughput measurement.

## Fixed, active, recovered and retired ownership

Each pool ran at one and two concurrent registry operations. Every population retained a fixed snapshot, a physically observed held request, cancellation and recovery, one cold successful pull, three warm successful pulls, and shutdown. Each successful pull verified the exact three-byte blob and its digest.

| Held operation | Ceiling one | Ceiling two |
| --- | --- | --- |
| Token acquisition | One leader, no followers | One leader, one follower |
| Token acquisition reserved bytes | 65,536 | 65,536 |
| DNS lookup | One resolver, no waiters | One resolver, one waiter |
| DNS active plus fixed reservation | 65,696 bytes | 65,696 bytes |
| DNS fixed configuration/cache reservation | 160 bytes | 160 bytes |
| Approved redirect reservation | 16,384 bytes | 32,768 bytes |
| Redirect connection reservation | 262,144 bytes | 524,288 bytes |
| Retained registry-operation blob bytes | 3 | 6 |

All connection and token reservations stayed within their configured limits. Cold and warm pulls retained one 22-byte token per client. DNS kept one bounded cached answer and its fixed 160-byte configuration/cache reservation. These are accounting charges, not allocator or process RSS measurements. Token and DNS retained bytes plateaued across all four successful pulls.

Cancellation aborted every caller before awaiting any of them, preventing a surviving follower from taking over token acquisition. The token/storage TLS peers observed physical connection closure. Registry in-flight work, bearer leaders/followers, DNS resolver jobs/waiters, live connections, connection reservations and redirect reservations all returned to zero. Shutdown closed all three owners and removed cached token/answer entries; configured DNS metadata remained separately measured.

After every owned peer was stopped and joined, the same process returned to two threads, seven file descriptors and zero sockets, matching its initial snapshot. RSS changed from 6,684,672 to 13,893,632 bytes. The campaign does not equate allocator retention with a leaked active owner or promise exact RSS return.

## Observed pull latency

| Pool / concurrency ceiling | Cold pull | Three warm pulls, minimum to maximum |
| --- | ---: | ---: |
| Token / one | 4.336 ms | 1.378–1.533 ms |
| DNS / one | 4.505 ms | 1.366–1.430 ms |
| Redirect / one | 3.199 ms | 3.095–3.214 ms |
| Token / two | 3.908 ms | 1.339–2.465 ms |
| DNS / two | 4.440 ms | 1.367–1.400 ms |
| Redirect / two | 3.148 ms | 3.105–5.059 ms |

The held/cancelled population exercises each ceiling; successful cold/warm pulls are sequential. These local-peer timings cannot establish network service latency or a universal hardware comparison. Approved storage redirects also verify that registry authorization and cookies are not forwarded.

## Reproduction and regression boundary

```sh
python3 tools/phase3_resource_oci.py --revision FULL_TESTED_COMMIT --output /workspace/target/oci-run.json --report /workspace/target/oci-observations.json --host-condition shared-docker-desktop-wsl2
python3 -m unittest tools.tests.test_phase3_resource tools.tests.test_phase3_resource_oci
cargo test --locked -p latent-oci --lib
```

The manual case is explicitly ignored in ordinary CI. Its runner requires a fresh absolute output/report path, exact nonempty test listing, bounded subprocess output and deadlines, unchanged source/binary identities and complete observations. Small tests reject incomplete populations, wrong artifacts, unbounded reservations, retained active owners and unreaped peers. All 54 ordinary OCI tests passed with the manual case explicitly ignored. The unconditional workspace dependency graph also passed.

The [earlier execution](phase3-resource-evidence/2026-09-21-oci-run.json) and [earlier observations](phase3-resource-evidence/2026-09-21-oci-observations.json) remain unchanged. That source used the higher-level testkit process probe: measurements passed, but CI correctly rejected the new dependency cycle. The current probe reads only this process's bounded Linux status and descriptor population and introduces no node/provider dependency into OCI.

Together with the [provider checkpoint](phase3-resource-events.md), [standalone provider profiles](phase3-resource-recovery.md), and [renderer/shared-storage measurements](phase3-resource-renderer.md), these observations cover the resource populations requested by #239. Each receipt retains its original source and pending ticket status. Ticket closure and the overall Phase 3 gate require the reviewed integration and their separate dependency evidence.
