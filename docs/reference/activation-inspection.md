# Authorized activation inspection

Use the configured tenant administrator credential and the supported CLI:

```powershell
latent activation tree ROOT_OR_CHILD_ID --page-size 32 --output json
latent activation tree ROOT_OR_CHILD_ID --page-size 32 --page-token OPAQUE_TOKEN --output json
```

`NodeService.InspectActivationTree` is a read-only management RPC. A tenant
administrator may read each retained node and edge in their tenant. Parent,
root and child IDs confer no result access, cancellation permission or authority
to another tenant. External invocation requests cannot forge lineage; only the
trusted broker creates child edges against its live parent owner.

The response is schema version 1. It contains only bounded identity links,
phase/terminal category, update time, actual trusted caller class and service,
and the admitted budget and effective deadline when admission occurred. It
never includes subject/claims, guest payload/result, arbitrary error message,
function/type names, provider configuration, paths or credential material.

Diagnostics are producer-owned numeric stage/reason/profile observations and
optional profile digest, configured bound and computed allocation terms.
Missing fields remain unknown; an allocation-limit or generic resource error
does not imply guest memory exhaustion. Signature/value limits, unsupported
surface/profile, missing provider/binding, admission/grant denial, queue
pressure, guest memory/fuel/resource exhaustion and provider timeout use
different reasons. Unknown client enum numbers are preserved as numbers.
`diagnosticIsTerminal` distinguishes the actual terminal failure cause from a
caught broker observation; a successful guest may have caught a provider error.

One request returns at most 128 nodes and 64 KiB. Zero/absent size selects 32;
clients never drain pages automatically. Cursors are opaque and tied to tenant,
anchor, retained anchor identity and this journal lifetime. Their membership
horizon excludes children created after the first page; mutable outcomes can
advance between pages. Forged or mismatched retained cursors reject.

The index has one entry per existing journal record and shares its byte/count
budgets, lock, terminal FIFO eviction and monotonic retention. Active records
are not evicted. No per-deployment watcher, graph store or payload journal is
created. Missing, foreign, expired or evicted anchors are indistinguishable:
`historyAvailable=false`. `retainedHistoryOnly=true` always; an expired cursor
is reported explicitly when its anchor has disappeared. Missing ancestors and
absence of capability telemetry never certify a complete history or prove no
external mutation. Terminal execution and physical provider cleanup remain
separate; `externalCompletion` is `unknown` in CLI output.

The shared client profile includes this RPC in Rust, Go, C, Java, .NET and
TypeScript's explicit Node transport. Browser-safe facades do not expose an
authenticated operator transport. The common fixtures cover absence, zero,
full-width unsigned values, unknown enum numbers and early preparation failure.
Final workload qualification uses the synthetic Java adapter/domain fixture
from #708 with the actual packaged node profile; facade or fixture compilation
alone is not that qualification.
