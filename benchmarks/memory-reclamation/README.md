# Memory return after activation bursts

Phase 1 retains bounded cleanup proofs and mixed-workload resource soaks; see the [completion review](../../docs/phase-1-completion.md). The metrics below define the broader benchmark specification. `post_gc_rss_bytes` is a historical metric label; the Rust/Wasmtime runtime does not promise a tracing-GC cycle or that every allocator/cache page returns to the OS after an activation.

## Required metrics

- `baseline_rss_bytes`
- `peak_rss_bytes`
- `post_gc_rss_bytes`
- `retained_cache_bytes`

## Required variants

- cold artifact cache
- warm raw artifact cache
- warm AOT cache
- mapped/prepared cache where applicable
- success and bounded failure paths
