# AbortSignal engine stack integration

PR #1934 is restacked onto parent commit
`5857840d85dc06e2658c5d8bcddda0103e2a2dce` with a history-preserving merge.
The registered WeakCache, foreground finalization, dependent liveness and
callback-lookup corrections from `a30f763762a87d1332e100a00c4b65d37babfb7d`
remain present. The merge preserves the parent's mandatory compiler guard,
newer capture-retirement controls, timer fairness, exact retirement-token
retries, and disjoint signed Fetch probe dispatch modes.

## Validation executed on 2026-11-10

The source projection's changed files were checked against their Git blob
identities before publication. The following local commands completed:

```sh
python -B -m unittest tools.tests.test_typescript_event_ownership \
  tools.tests.test_typescript_abort_any_ownership \
  tools.tests.test_typescript_record_retirement.OwnerRetryTests \
  tools.tests.test_typescript_record_retirement.QueueCancellationTests \
  tools.tests.test_typescript_abort_stack_integration -v
```

This GCC selection passed 38 test methods. The same selection without the
separate abort-any module passed 34 methods with Clang, and 34 with the
maintained ASan/UBSan compiler wrapper. Leak detection and halt-on-error
remained enabled; no sanitizer suppression was added. Counts describe these
observed executions, not a required test inventory.

These controls exercise emitted source, physical native-record destruction,
refused acknowledgements, callback failure, graph liveness/relocation doubles,
probe dispatch, and an actual Wasm trap of production frame leases. The GC
controls use finite doubles, not a live SpiderMonkey collector. The Node probe
control is not signed LSF execution. The entire current development checkout,
fresh linked source-built engine, signed guest, pool failure/quarantine and
cross-tenant reuse are not qualified by these results. Historical compiled
engines have a different source identity and cannot substitute for this build.

No grants, owner ceilings, memory limits, deadlines, expected success results,
issue acceptance checkboxes or runtime support claims are widened.
